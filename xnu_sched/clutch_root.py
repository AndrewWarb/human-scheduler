"""
ClutchRoot: root of the Clutch scheduler hierarchy per cluster.

Faithfully ports sched_clutch_root from sched_clutch.h:129-181 and the
root bucket selection algorithm from sched_clutch.c:838-1037.

This is the core scheduling decision engine that implements:
- EDF (Earliest Deadline First) scheduling among QoS root buckets
- Warp mechanism for higher-priority buckets to jump ahead temporarily
- Starvation avoidance for lower-priority buckets
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .constants import (
    TH_BUCKET_FIXPRI,
    TH_BUCKET_SHARE_FG,
    TH_BUCKET_SCHED_MAX,
    NOPRI,
    ROOT_BUCKET_WARP_US,
    SCHED_CLUTCH_ROOT_BUCKET_WARP_UNUSED,
    THREAD_QUANTUM_US,
    SCHED_CLUTCH_BUCKET_OPTIONS_HEADQ,
    SCHED_CLUTCH_BUCKET_OPTIONS_TAILQ,
    SCHED_CLUTCH_BUCKET_OPTIONS_SAMEPRI_RR,
    is_above_timeshare,
    BUCKET_NAMES,
)
from .root_bucket import ClutchRootBucket
from .clutch import SchedClutchBucket, SchedClutchBucketGroup
from .priority_queue import PriorityQueueDeadlineMin

if TYPE_CHECKING:
    from .thread import Thread


def _pri_greater_tiebreak(pri_one: int, pri_two: int, one_wins_ties: bool) -> bool:
    """Port of sched_clutch_pri_greater_than_tiebreak (sched_clutch.c:3318-3325)."""
    if one_wins_ties:
        return pri_one >= pri_two
    return pri_one > pri_two


class ClutchRoot:
    """Root of the Clutch hierarchy for a single cluster.

    Manages root buckets and implements the three-phase selection:
    1. Above UI (FIXPRI) check
    2. EDF among timeshare root buckets
    3. Warp and starvation avoidance
    """

    __slots__ = (
        "scr_cluster_id",
        "scr_priority",
        "scr_thr_count",
        "scr_urgency",
        # Unbound root buckets
        "scr_unbound_buckets",
        "scr_unbound_root_prioq",
        "scr_unbound_runnable_bitmap",
        "scr_unbound_warp_available",
        # Bound root buckets
        "scr_bound_buckets",
        "scr_bound_root_prioq",
        "scr_bound_runnable_bitmap",
        "scr_bound_warp_available",
        # Global bucket load tracking
        "scr_global_bucket_load",
        # All runnable clutch buckets (for sched_tick iteration)
        "scr_clutch_buckets_list",
    )

    def __init__(self, cluster_id: int = 0) -> None:
        self.scr_cluster_id = cluster_id
        self.scr_priority: int = NOPRI
        self.scr_thr_count: int = 0
        self.scr_urgency: int = 0

        # Initialize unbound root buckets
        self.scr_unbound_buckets: list[ClutchRootBucket] = [
            ClutchRootBucket(bucket, bound=False) for bucket in range(TH_BUCKET_SCHED_MAX)
        ]
        self.scr_unbound_root_prioq = PriorityQueueDeadlineMin[ClutchRootBucket](
            deadline_fn=lambda rb: rb.scrb_deadline
        )
        self.scr_unbound_runnable_bitmap: int = 0
        self.scr_unbound_warp_available: int = 0

        # Initialize bound root buckets
        self.scr_bound_buckets: list[ClutchRootBucket] = [
            ClutchRootBucket(bucket, bound=True) for bucket in range(TH_BUCKET_SCHED_MAX)
        ]
        self.scr_bound_root_prioq = PriorityQueueDeadlineMin[ClutchRootBucket](
            deadline_fn=lambda rb: rb.scrb_deadline
        )
        self.scr_bound_runnable_bitmap: int = 0
        self.scr_bound_warp_available: int = 0

        # Per-bucket global load (number of clutch buckets in each QoS)
        self.scr_global_bucket_load: list[int] = [0] * TH_BUCKET_SCHED_MAX

        # List of all runnable clutch buckets
        self.scr_clutch_buckets_list: list[SchedClutchBucket] = []

    # ------------------------------------------------------------------
    # Bitmap helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _bitmap_lsb_first(bitmap: int, max_bits: int) -> int:
        """Find lowest set bit (highest priority bucket). Returns -1 if none."""
        if bitmap == 0:
            return -1
        return (bitmap & -bitmap).bit_length() - 1

    @staticmethod
    def _bitmap_set(bitmap: int, bit: int) -> int:
        return bitmap | (1 << bit)

    @staticmethod
    def _bitmap_clear(bitmap: int, bit: int) -> int:
        return bitmap & ~(1 << bit)

    @staticmethod
    def _bitmap_test(bitmap: int, bit: int) -> bool:
        return bool(bitmap & (1 << bit))

    # ------------------------------------------------------------------
    # Root bucket lifecycle
    # ------------------------------------------------------------------
    def root_bucket_runnable(
        self, root_bucket: ClutchRootBucket, timestamp: int
    ) -> None:
        """Insert a newly runnable root bucket into the hierarchy.

        Ports sched_clutch_root_bucket_runnable() (sched_clutch.c:1103-1133).
        """
        if root_bucket.scrb_bound:
            self.scr_bound_runnable_bitmap = self._bitmap_set(
                self.scr_bound_runnable_bitmap, root_bucket.scrb_bucket
            )
        else:
            self.scr_unbound_runnable_bitmap = self._bitmap_set(
                self.scr_unbound_runnable_bitmap, root_bucket.scrb_bucket
            )

        if is_above_timeshare(root_bucket.scrb_bucket):
            return

        # Set deadline unless in starvation avoidance
        if not root_bucket.scrb_starvation_avoidance:
            root_bucket.scrb_deadline = root_bucket.deadline_calculate(timestamp)

        prioq = (
            self.scr_bound_root_prioq
            if root_bucket.scrb_bound
            else self.scr_unbound_root_prioq
        )
        prioq.insert(root_bucket)

        if root_bucket.scrb_warp_remaining > 0:
            if root_bucket.scrb_bound:
                self.scr_bound_warp_available = self._bitmap_set(
                    self.scr_bound_warp_available, root_bucket.scrb_bucket
                )
            else:
                self.scr_unbound_warp_available = self._bitmap_set(
                    self.scr_unbound_warp_available, root_bucket.scrb_bucket
                )

    def root_bucket_empty(
        self, root_bucket: ClutchRootBucket, timestamp: int
    ) -> None:
        """Remove an empty root bucket from the hierarchy.

        Ports sched_clutch_root_bucket_empty() (sched_clutch.c:1141-1179).
        """
        if root_bucket.scrb_bound:
            self.scr_bound_runnable_bitmap = self._bitmap_clear(
                self.scr_bound_runnable_bitmap, root_bucket.scrb_bucket
            )
        else:
            self.scr_unbound_runnable_bitmap = self._bitmap_clear(
                self.scr_unbound_runnable_bitmap, root_bucket.scrb_bucket
            )

        if is_above_timeshare(root_bucket.scrb_bucket):
            return

        prioq = (
            self.scr_bound_root_prioq
            if root_bucket.scrb_bound
            else self.scr_unbound_root_prioq
        )
        prioq.remove(root_bucket)

        if root_bucket.scrb_bound:
            self.scr_bound_warp_available = self._bitmap_clear(
                self.scr_bound_warp_available, root_bucket.scrb_bucket
            )
        else:
            self.scr_unbound_warp_available = self._bitmap_clear(
                self.scr_unbound_warp_available, root_bucket.scrb_bucket
            )

        root_bucket.on_empty(timestamp)

    # ------------------------------------------------------------------
    # Clutch bucket insertion into root bucket hierarchy
    # ------------------------------------------------------------------
    def clutch_bucket_hierarchy_insert(
        self,
        clutch_bucket: SchedClutchBucket,
        bucket: int,
        timestamp: int,
        options: int,
    ) -> None:
        """Insert a clutch bucket into the appropriate root bucket.

        Ports sched_clutch_bucket_hierarchy_insert().
        """
        root_bucket = self.scr_unbound_buckets[bucket]
        was_empty = root_bucket.scrb_clutch_buckets.empty()

        head = bool(options & SCHED_CLUTCH_BUCKET_OPTIONS_HEADQ)
        root_bucket.scrb_clutch_buckets.enqueue(
            clutch_bucket, clutch_bucket.scb_priority, head=head
        )
        clutch_bucket.scb_root = self

        self.scr_clutch_buckets_list.append(clutch_bucket)
        self.scr_global_bucket_load[bucket] += 1

        if was_empty:
            self.root_bucket_runnable(root_bucket, timestamp)

    def clutch_bucket_hierarchy_remove(
        self,
        clutch_bucket: SchedClutchBucket,
        bucket: int,
        timestamp: int,
        options: int,
    ) -> None:
        """Remove a clutch bucket from its root bucket."""
        root_bucket = self.scr_unbound_buckets[bucket]

        root_bucket.scrb_clutch_buckets.dequeue(
            clutch_bucket, clutch_bucket.scb_priority
        )
        clutch_bucket.scb_root = None

        if clutch_bucket in self.scr_clutch_buckets_list:
            self.scr_clutch_buckets_list.remove(clutch_bucket)
        self.scr_global_bucket_load[bucket] -= 1

        if root_bucket.scrb_clutch_buckets.empty():
            self.root_bucket_empty(root_bucket, timestamp)

    # ------------------------------------------------------------------
    # Clutch bucket runnable/update/empty (called during thread insert/remove)
    # ------------------------------------------------------------------
    def clutch_bucket_runnable(
        self,
        clutch_bucket: SchedClutchBucket,
        timestamp: int,
        options: int,
    ) -> bool:
        """Handle a clutch bucket becoming runnable (first thread added).

        Ports sched_clutch_bucket_runnable() (sched_clutch.c:1789-1807).
        Returns True if root priority increased.
        """
        clutch_bucket.scb_priority = clutch_bucket.pri_calculate(
            timestamp, self.scr_global_bucket_load[clutch_bucket.scb_bucket]
        )
        self.clutch_bucket_hierarchy_insert(
            clutch_bucket, clutch_bucket.scb_bucket, timestamp, options
        )
        clutch_bucket.scb_group.pri_shift_update(0, 1)  # Will be updated properly by scheduler

        old_pri = self.scr_priority
        self.root_pri_update()
        return self.scr_priority > old_pri

    def clutch_bucket_update(
        self,
        clutch_bucket: SchedClutchBucket,
        timestamp: int,
        options: int,
    ) -> bool:
        """Update a clutch bucket's position (thread added/removed but bucket not empty).

        Ports sched_clutch_bucket_update() (sched_clutch.c:1817-1856).
        Returns True if root priority increased.
        """
        new_pri = clutch_bucket.pri_calculate(
            timestamp, self.scr_global_bucket_load[clutch_bucket.scb_bucket]
        )
        root_bucket = self.scr_unbound_buckets[clutch_bucket.scb_bucket]
        bucket_runq = root_bucket.scrb_clutch_buckets

        if new_pri == clutch_bucket.scb_priority:
            if options & SCHED_CLUTCH_BUCKET_OPTIONS_SAMEPRI_RR:
                bucket_runq.rotate_at(clutch_bucket.scb_priority)
            return False

        # Priority changed: remove and re-insert
        bucket_runq.dequeue(clutch_bucket, clutch_bucket.scb_priority)
        clutch_bucket.scb_priority = new_pri
        head = bool(options & SCHED_CLUTCH_BUCKET_OPTIONS_HEADQ)
        bucket_runq.enqueue(clutch_bucket, new_pri, head=head)

        old_pri = self.scr_priority
        self.root_pri_update()
        return self.scr_priority > old_pri

    def clutch_bucket_empty(
        self,
        clutch_bucket: SchedClutchBucket,
        timestamp: int,
        options: int,
    ) -> None:
        """Handle a clutch bucket becoming empty (last thread removed).

        Ports sched_clutch_bucket_empty() (sched_clutch.c:1865-1881).
        """
        self.clutch_bucket_hierarchy_remove(
            clutch_bucket, clutch_bucket.scb_bucket, timestamp, options
        )
        clutch_bucket.scb_group.pri_shift_update(0, 1)
        clutch_bucket.scb_priority = 0
        self.root_pri_update()

    # ------------------------------------------------------------------
    # Root priority update (sched_clutch.c:1204-1280)
    # ------------------------------------------------------------------
    def root_pri_update(self) -> None:
        """Update root priority to reflect the highest runnable thread.

        Ports sched_clutch_root_pri_update() for unbound Clutch hierarchy.

        Important XNU parity detail: root priority is based on highest runnable
        thread priority within the selected root bucket, not the clutch bucket's
        interactivity-adjusted priority.
        """
        root_unbound_pri = NOPRI
        highest_unbound_root_bucket: ClutchRootBucket | None = None
        highest_unbound_root_bucket_pri = -1
        highest_unbound_root_bucket_is_fixpri = False

        # Select between unbound FIXPRI and SHARE_FG using AboveUI comparison.
        if self._bitmap_test(self.scr_unbound_runnable_bitmap, TH_BUCKET_FIXPRI):
            fixpri_rb = self.scr_unbound_buckets[TH_BUCKET_FIXPRI]
            if not fixpri_rb.scrb_clutch_buckets.empty():
                highest_unbound_root_bucket = fixpri_rb
                highest_unbound_root_bucket_pri = (
                    fixpri_rb.scrb_clutch_buckets.peek_highest().scb_priority
                )
                highest_unbound_root_bucket_is_fixpri = True

        if self._bitmap_test(self.scr_unbound_runnable_bitmap, TH_BUCKET_SHARE_FG):
            fg_rb = self.scr_unbound_buckets[TH_BUCKET_SHARE_FG]
            if not fg_rb.scrb_clutch_buckets.empty():
                fg_pri = fg_rb.scrb_clutch_buckets.peek_highest().scb_priority
                if (
                    highest_unbound_root_bucket is None
                    or fg_pri > highest_unbound_root_bucket_pri
                ):
                    highest_unbound_root_bucket = fg_rb
                    highest_unbound_root_bucket_pri = fg_pri
                    highest_unbound_root_bucket_is_fixpri = False

        # If AboveUI didn't choose FIXPRI, use highest runnable timeshare bucket.
        if highest_unbound_root_bucket is not None and not highest_unbound_root_bucket_is_fixpri:
            highest_unbound_root_bucket = None
            for bucket_idx in range(TH_BUCKET_SHARE_FG, TH_BUCKET_SCHED_MAX):
                if self._bitmap_test(self.scr_unbound_runnable_bitmap, bucket_idx):
                    rb = self.scr_unbound_buckets[bucket_idx]
                    if not rb.scrb_clutch_buckets.empty():
                        highest_unbound_root_bucket = rb
                        break

        # Fallback: if neither FIXPRI nor FG was selected above, choose first runnable.
        if highest_unbound_root_bucket is None:
            for bucket_idx in range(TH_BUCKET_SCHED_MAX):
                if self._bitmap_test(self.scr_unbound_runnable_bitmap, bucket_idx):
                    rb = self.scr_unbound_buckets[bucket_idx]
                    if not rb.scrb_clutch_buckets.empty():
                        highest_unbound_root_bucket = rb
                        break

        if highest_unbound_root_bucket is not None:
            clutch_bucket, _ = self.root_bucket_highest_clutch_bucket(highest_unbound_root_bucket)
            if (
                clutch_bucket is not None
                and not clutch_bucket.scb_clutchpri_prioq.empty()
            ):
                root_unbound_pri = clutch_bucket.scb_clutchpri_prioq.max_priority()

        self.scr_priority = root_unbound_pri

    # ------------------------------------------------------------------
    # Root bucket selection: the core EDF + warp + starvation algorithm
    # Ports sched_clutch_root_highest_root_bucket() (sched_clutch.c:838-1037)
    # ------------------------------------------------------------------
    def highest_root_bucket(
        self,
        timestamp: int,
        prev_bucket: ClutchRootBucket | None = None,
        prev_thread: Thread | None = None,
    ) -> tuple[ClutchRootBucket | None, bool]:
        """Select the highest-priority root bucket using EDF + warp + starvation.

        This is the heart of the Clutch scheduler's root-level policy.
        Faithfully ports sched_clutch_root_highest_root_bucket() (sched_clutch.c:838-1037).

        When prev_thread is provided, its root bucket (prev_bucket) is considered
        as a candidate even though the thread hasn't been re-enqueued yet. This
        matches XNU's select-then-dispatch flow.

        Returns (root_bucket, chose_prev) where chose_prev=True means the
        prev_thread's bucket was selected and the caller should keep running it.
        """
        highest_runnable = self._highest_runnable_qos()
        has_prev = prev_bucket is not None and prev_thread is not None

        if highest_runnable == -1 and not has_prev:
            return None, False

        if highest_runnable == -1 and has_prev:
            # No enqueued buckets, but prev_thread's bucket is available
            return prev_bucket, True

        # Phase 1: AboveUI check — compare FIXPRI vs SHARE_FG only
        # Ports sched_clutch_root_highest_aboveui_root_bucket (sched_clutch.c:777-826)
        # and sched_clutch_root_unbound_select_aboveui (sched_clutch.c:641-697)
        fixpri_runnable = self._bitmap_test(
            self.scr_unbound_runnable_bitmap, TH_BUCKET_FIXPRI
        )
        prev_is_fixpri = has_prev and prev_bucket.scrb_bucket == TH_BUCKET_FIXPRI

        if fixpri_runnable or prev_is_fixpri:
            aboveui_result = self._select_aboveui(
                prev_bucket, prev_thread, has_prev
            )
            if aboveui_result is not None:
                return aboveui_result

        # Phase 2: EDF among timeshare root buckets
        return self._evaluate_root_buckets(timestamp, prev_bucket, prev_thread)

    def _select_aboveui(
        self,
        prev_bucket: ClutchRootBucket | None,
        prev_thread: Thread | None,
        has_prev: bool,
    ) -> tuple[ClutchRootBucket, bool] | None:
        """Determine if FIXPRI should bypass EDF by comparing against SHARE_FG.

        Ports sched_clutch_root_unbound_select_aboveui (sched_clutch.c:641-697)
        and the chose_prev logic from sched_clutch_root_highest_aboveui_root_bucket
        (sched_clutch.c:817-825).

        Returns (root_bucket, chose_prev) if AboveUI wins, None if EDF should decide.
        """
        higher_root_bucket: ClutchRootBucket | None = None
        higher_clutch_bucket: SchedClutchBucket | None = None
        higher_is_aboveui = False

        # Consider unbound Above UI (FIXPRI)
        if self._bitmap_test(self.scr_unbound_runnable_bitmap, TH_BUCKET_FIXPRI):
            fixpri_rb = self.scr_unbound_buckets[TH_BUCKET_FIXPRI]
            if not fixpri_rb.scrb_clutch_buckets.empty():
                higher_root_bucket = fixpri_rb
                higher_clutch_bucket = fixpri_rb.scrb_clutch_buckets.peek_highest()
                higher_is_aboveui = True

        # Consider unbound Timeshare FG only (strict > because FG loses ties)
        # XNU line 666: clutch_bucket_sharefg->scb_priority > higher_clutch_bucket->scb_priority
        if self._bitmap_test(self.scr_unbound_runnable_bitmap, TH_BUCKET_SHARE_FG):
            fg_rb = self.scr_unbound_buckets[TH_BUCKET_SHARE_FG]
            if not fg_rb.scrb_clutch_buckets.empty():
                fg_cb = fg_rb.scrb_clutch_buckets.peek_highest()
                if (
                    higher_root_bucket is None
                    or fg_cb.scb_priority > higher_clutch_bucket.scb_priority
                ):
                    higher_root_bucket = fg_rb
                    higher_clutch_bucket = fg_cb
                    higher_is_aboveui = False

        # Consider prev_thread using interactivity-adjusted clutch bucket priority
        # XNU line 677: prev_clutch_bucket_pri = sched_pri + interactivity_count
        if has_prev and prev_thread.thread_group.sched_clutch is not None:
            prev_cbg = prev_thread.thread_group.sched_clutch.sc_clutch_groups[
                prev_thread.th_sched_bucket
            ]
            prev_clutch_bucket_pri = (
                prev_thread.sched_pri + prev_cbg.scbg_interactivity_score
            )
            # XNU line 679: FIXPRI prev wins ties only if current winner is not AboveUI
            prev_should_win_ties = (
                prev_bucket.scrb_bucket == TH_BUCKET_FIXPRI
                and not higher_is_aboveui
            )
            if higher_clutch_bucket is None or _pri_greater_tiebreak(
                prev_clutch_bucket_pri,
                higher_clutch_bucket.scb_priority,
                prev_should_win_ties,
            ):
                higher_root_bucket = prev_bucket
                higher_is_aboveui = (
                    prev_bucket.scrb_bucket == TH_BUCKET_FIXPRI
                )

        if higher_root_bucket is None or not higher_is_aboveui:
            return None  # AboveUI doesn't win; use EDF

        # AboveUI wins. Check if chose_prev (winning bucket is empty in bitmap,
        # meaning prev_thread is the only candidate). XNU line 818-823.
        chose_prev = False
        if has_prev and not self._bitmap_test(
            self.scr_unbound_runnable_bitmap, higher_root_bucket.scrb_bucket
        ):
            chose_prev = True

        return higher_root_bucket, chose_prev

    def _evaluate_root_buckets(
        self,
        timestamp: int,
        prev_bucket: ClutchRootBucket | None = None,
        prev_thread: Thread | None = None,
    ) -> tuple[ClutchRootBucket | None, bool]:
        """EDF evaluation with starvation avoidance and warp.

        Faithfully ports the evaluate_root_buckets: label loop in
        sched_clutch.c:886-1037. When prev_bucket is provided, it competes
        in EDF even though it's not in the priority queue.

        Key XNU details ported:
        - prev_bucket replaces edf_bucket inline (not early return)
        - edf_bucket_enqueued_normally tracks whether to update priority queue
        - Starvation check happens AFTER prev_bucket EDF comparison
        - prev_bucket can warp; bitmap clear skipped for prev_bucket warp

        Returns (root_bucket, chose_prev).
        """
        has_prev = prev_bucket is not None and prev_thread is not None
        prev_in_edf = has_prev and not is_above_timeshare(prev_bucket.scrb_bucket)

        while True:
            # evaluate_root_buckets: label
            edf_bucket = self.scr_unbound_root_prioq.peek_min()
            edf_bucket_enqueued_normally = True

            if edf_bucket is None:
                # Timeshare portion of queue is empty
                if prev_in_edf:
                    return prev_bucket, True
                return None, False

            # XNU line 913-917: Compare prev_bucket deadline against EDF winner
            # Uses strict < (not <=). prev_bucket replaces edf_bucket inline.
            if prev_in_edf and prev_bucket is not edf_bucket:
                if prev_bucket.scrb_deadline < edf_bucket.scrb_deadline:
                    edf_bucket = prev_bucket
                    edf_bucket_enqueued_normally = False

            # XNU line 919-930: Check starvation avoidance expiry
            # (runs on whichever bucket won the EDF comparison above)
            if edf_bucket.scrb_starvation_avoidance:
                starvation_window = THREAD_QUANTUM_US[edf_bucket.scrb_bucket]
                if timestamp >= edf_bucket.scrb_starvation_ts + starvation_window:
                    edf_bucket.scrb_starvation_avoidance = False
                    edf_bucket.scrb_starvation_ts = 0
                    edf_bucket.deadline_update(timestamp)
                    if edf_bucket_enqueued_normally:
                        self.scr_unbound_root_prioq.update_deadline(edf_bucket)
                    continue  # goto evaluate_root_buckets

            # XNU line 938-946: Check warp availability
            warp_bitmap = self.scr_unbound_warp_available
            warp_bucket_index = self._bitmap_lsb_first(warp_bitmap, TH_BUCKET_SCHED_MAX)

            # XNU line 942-944: Allow prev_bucket to use its warp
            # (only if prev_bucket is NOT already the EDF winner)
            prev_bucket_warping = (
                prev_in_edf
                and prev_bucket is not edf_bucket
                and prev_bucket.scrb_warp_remaining > 0
                and prev_bucket.scrb_bucket < edf_bucket.scrb_bucket
                and (warp_bucket_index == -1 or prev_bucket.scrb_bucket < warp_bucket_index)
            )

            # XNU line 946
            non_edf_can_warp = (
                (warp_bucket_index != -1 and warp_bucket_index < edf_bucket.scrb_bucket)
                or prev_bucket_warping
            )

            if not non_edf_can_warp:
                # XNU line 948-983: No higher buckets have warp; EDF bucket wins
                self._handle_edf_selection(
                    edf_bucket, timestamp, prev_bucket, edf_bucket_enqueued_normally
                )
                return edf_bucket, not edf_bucket_enqueued_normally

            # XNU line 989-996: Select warp bucket
            if prev_bucket_warping:
                warp_bucket = prev_bucket
            else:
                warp_bucket = self.scr_unbound_buckets[warp_bucket_index]

            # XNU line 1000-1011: Warp unused
            if warp_bucket.scrb_warped_deadline == SCHED_CLUTCH_ROOT_BUCKET_WARP_UNUSED:
                warp_bucket.scrb_warped_deadline = (
                    timestamp + warp_bucket.scrb_warp_remaining
                )
                warp_bucket.deadline_update(timestamp)
                if not prev_bucket_warping:
                    self.scr_unbound_root_prioq.update_deadline(warp_bucket)
                return warp_bucket, prev_bucket_warping

            # XNU line 1012-1020: Warp window still open
            if warp_bucket.scrb_warped_deadline > timestamp:
                warp_bucket.deadline_update(timestamp)
                if not prev_bucket_warping:
                    self.scr_unbound_root_prioq.update_deadline(warp_bucket)
                return warp_bucket, prev_bucket_warping

            # XNU line 1022-1036: Warp expired
            warp_bucket.scrb_warp_remaining = 0
            if not prev_bucket_warping:
                # XNU line 1028: Only clear bitmap for normally-enqueued buckets
                self.scr_unbound_warp_available = self._bitmap_clear(
                    self.scr_unbound_warp_available, warp_bucket.scrb_bucket
                )
            continue  # goto evaluate_root_buckets

    def _handle_edf_selection(
        self,
        edf_bucket: ClutchRootBucket,
        timestamp: int,
        prev_bucket: ClutchRootBucket | None = None,
        edf_bucket_enqueued_normally: bool = True,
    ) -> None:
        """Handle EDF bucket selection: starvation avoidance and deadline/warp reset.

        Faithfully ports the non_edf_bucket_can_warp == false branch
        (sched_clutch.c:948-983).

        When edf_bucket_enqueued_normally is False (meaning edf_bucket IS
        prev_bucket), priority queue updates and warp bitmap sets are skipped
        because the bucket isn't in the queue.
        """
        highest_runnable = self._highest_runnable_qos()

        # XNU line 955: Also consider prev_bucket's QoS for starvation check
        if prev_bucket is not None and not is_above_timeshare(prev_bucket.scrb_bucket):
            if highest_runnable == -1 or prev_bucket.scrb_bucket < highest_runnable:
                highest_runnable = prev_bucket.scrb_bucket

        if not edf_bucket.scrb_starvation_avoidance:
            if highest_runnable != -1 and highest_runnable < edf_bucket.scrb_bucket:
                # Higher-priority bucket is runnable but EDF chose lower bucket
                # -> enter starvation avoidance mode
                edf_bucket.scrb_starvation_avoidance = True
                edf_bucket.scrb_starvation_ts = timestamp
            else:
                # Natural EDF order: update deadline and reset warp
                edf_bucket.deadline_update(timestamp)
                # XNU line 972: Only update priority queue if bucket is enqueued
                if edf_bucket_enqueued_normally:
                    self.scr_unbound_root_prioq.update_deadline(edf_bucket)
                edf_bucket.scrb_warp_remaining = ROOT_BUCKET_WARP_US[
                    edf_bucket.scrb_bucket
                ]
                edf_bucket.scrb_warped_deadline = SCHED_CLUTCH_ROOT_BUCKET_WARP_UNUSED
                # XNU line 972-978: Only set warp bitmap if bucket is enqueued
                if edf_bucket_enqueued_normally:
                    self.scr_unbound_warp_available = self._bitmap_set(
                        self.scr_unbound_warp_available, edf_bucket.scrb_bucket
                    )

    def _highest_runnable_qos(self) -> int:
        """Find the highest-priority (lowest index) runnable QoS bucket.

        Returns -1 if no bucket is runnable. Checks both FIXPRI and timeshare.
        """
        combined = self.scr_unbound_runnable_bitmap | self.scr_bound_runnable_bitmap
        return self._bitmap_lsb_first(combined, TH_BUCKET_SCHED_MAX)

    # ------------------------------------------------------------------
    # Highest clutch bucket within a root bucket (sched_clutch.c:1751-1780)
    # ------------------------------------------------------------------
    def root_bucket_highest_clutch_bucket(
        self,
        root_bucket: ClutchRootBucket,
        prev_thread: Thread | None = None,
        first_timeslice: bool = True,
    ) -> tuple[SchedClutchBucket | None, bool]:
        """Find the highest priority clutch bucket in a root bucket.

        Ports sched_clutch_root_bucket_highest_clutch_bucket (sched_clutch.c:1751-1780).
        Considers prev_thread's clutch bucket using interactivity-adjusted priority.

        Returns (clutch_bucket, chose_prev).
        """
        if root_bucket.scrb_clutch_buckets.empty():
            if prev_thread is not None:
                # Root bucket queue is empty but prev_thread is in this bucket
                prev_clutch = prev_thread.thread_group.sched_clutch
                prev_cb = prev_clutch.sc_clutch_groups[
                    prev_thread.th_sched_bucket
                ].scbg_clutch_buckets[self.scr_cluster_id]
                return prev_cb, True
            return None, False

        clutch_bucket = root_bucket.scrb_clutch_buckets.peek_highest()

        # XNU line 1768-1777: Consider prev_thread's clutch bucket
        if prev_thread is not None:
            prev_clutch = prev_thread.thread_group.sched_clutch
            if prev_clutch is not None:
                prev_cbg = prev_clutch.sc_clutch_groups[
                    prev_thread.th_sched_bucket
                ]
                prev_clutch_bucket_pri = (
                    prev_thread.sched_pri + prev_cbg.scbg_interactivity_score
                )
                prev_cb = prev_cbg.scbg_clutch_buckets[self.scr_cluster_id]
                # Only compare if prev is in a DIFFERENT clutch bucket
                if prev_cb is not clutch_bucket:
                    if _pri_greater_tiebreak(
                        prev_clutch_bucket_pri,
                        clutch_bucket.scb_priority,
                        first_timeslice,
                    ):
                        return prev_cb, True

        return clutch_bucket, False

    # ------------------------------------------------------------------
    # Thread lookup in hierarchy (sched_clutch.c:2925-2981)
    # ------------------------------------------------------------------
    def hierarchy_thread_highest(
        self,
        timestamp: int,
        prev_thread: Thread | None = None,
        first_timeslice: bool = True,
    ) -> tuple[Thread | None, ClutchRootBucket | None, bool]:
        """Traverse the Clutch hierarchy and return the highest thread.

        Ports sched_clutch_hierarchy_thread_highest() (sched_clutch.c:2925-2981)
        and sched_clutch_thread_unbound_lookup() (sched_clutch.c:2867-2901).

        Three-level selection with prev_thread consideration at each level:
        1. Root bucket level: EDF + warp + starvation (prev_bucket in EDF)
        2. Clutch bucket level: interactivity-adjusted priority comparison
        3. Thread level: raw sched_pri comparison with first_timeslice tiebreak

        Returns (thread, root_bucket, chose_prev) or (None, None, False).
        """
        # Derive prev_bucket from prev_thread
        prev_bucket: ClutchRootBucket | None = None
        if prev_thread is not None and not prev_thread.is_realtime:
            clutch = prev_thread.thread_group.sched_clutch
            if clutch is not None:
                prev_bucket = self.scr_unbound_buckets[prev_thread.th_sched_bucket]

        root_bucket, chose_prev = self.highest_root_bucket(
            timestamp, prev_bucket, prev_thread
        )
        if root_bucket is None:
            return None, None, False

        if chose_prev:
            # prev_thread's bucket was selected — prev_thread itself is the winner
            return prev_thread, root_bucket, True

        # XNU line 2952-2954: If a different root bucket won, rule out prev_thread
        # at deeper levels. Only consider prev_thread if same root bucket.
        if root_bucket is not prev_bucket:
            prev_thread = None

        # Level 2: Find highest clutch bucket (considering prev_thread)
        # Ports sched_clutch_root_bucket_highest_clutch_bucket (sched_clutch.c:1751-1780)
        clutch_bucket, cb_chose_prev = self.root_bucket_highest_clutch_bucket(
            root_bucket, prev_thread, first_timeslice
        )
        if clutch_bucket is None:
            return None, root_bucket, False

        if cb_chose_prev:
            # prev_thread's clutch bucket won at interactivity level
            return prev_thread, root_bucket, True

        # Level 3: Find highest thread in clutch bucket
        thread = clutch_bucket.scb_thread_runq.peek_max()

        # XNU line 2894-2898: Consider prev_thread within the same clutch bucket
        if prev_thread is not None and thread is not None:
            prev_clutch = prev_thread.thread_group.sched_clutch
            if prev_clutch is not None:
                prev_cb = prev_clutch.sc_clutch_groups[
                    prev_thread.th_sched_bucket
                ].scbg_clutch_buckets[self.scr_cluster_id]
                if prev_cb is clutch_bucket:
                    if _pri_greater_tiebreak(
                        prev_thread.sched_pri,
                        thread.sched_pri,
                        first_timeslice,
                    ):
                        return prev_thread, root_bucket, True

        return thread, root_bucket, False

    def __repr__(self) -> str:
        runnable = []
        for b in range(TH_BUCKET_SCHED_MAX):
            if self._bitmap_test(self.scr_unbound_runnable_bitmap, b):
                runnable.append(BUCKET_NAMES.get(b, str(b)))
        return (
            f"ClutchRoot(cluster={self.scr_cluster_id}, "
            f"pri={self.scr_priority}, threads={self.scr_thr_count}, "
            f"runnable=[{', '.join(runnable)}])"
        )

    def __getstate__(self) -> dict:
        return {slot: getattr(self, slot) for slot in self.__slots__}

    def __setstate__(self, state: dict) -> None:
        for slot in self.__slots__:
            setattr(self, slot, state.get(slot))
        self.scr_unbound_root_prioq._deadline_fn = lambda rb: rb.scrb_deadline
        self.scr_bound_root_prioq._deadline_fn = lambda rb: rb.scrb_deadline
