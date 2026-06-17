import type { Metadata } from "next";
import { AuthGuard } from "@/components/AuthGuard";
import "./globals.css";

export const metadata: Metadata = {
  title: "financial-KDAF — Knowledge Engineer",
  description: "Enrichment task triage and KG write-back UI",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-gray-100 min-h-screen antialiased">
        <AuthGuard>{children}</AuthGuard>
      </body>
    </html>
  );
}
