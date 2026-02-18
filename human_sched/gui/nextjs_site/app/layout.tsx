import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Task Scheduler GUI",
  description: "Human Scheduler - Focus Control Panel",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
