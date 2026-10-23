import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Acquisitions Assistant AI",
  description:
    "Local seller-lead operations dashboard. REsimpli remains the source of truth. This app never contacts sellers automatically.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="min-w-0 flex-1 lg:ml-60">
            <div className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6 lg:px-8">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
