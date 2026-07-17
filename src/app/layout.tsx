import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Colinas Foods — Order Dashboard",
  description: "Web-based order management dashboard for Colinas Foods. Submit, review, and confirm sales orders.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
