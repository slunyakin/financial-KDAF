import type { Metadata } from "next";
import { AuthGuard } from "@/components/AuthGuard";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";

const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "financial-KDAF — Knowledge Engineer",
  description: "Enrichment task triage and KG write-back UI",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={cn("dark font-sans", geist.variable)}>
      <body className="bg-background text-foreground min-h-screen antialiased">
        <TooltipProvider>
          <AuthGuard>{children}</AuthGuard>
        </TooltipProvider>
      </body>
    </html>
  );
}
