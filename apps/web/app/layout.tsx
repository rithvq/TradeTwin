import type { Metadata } from "next";
import "@xyflow/react/dist/style.css";
import { AppShell } from "../components/app-shell";
import { QueryProvider } from "../components/providers/query-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "TradeTwin",
  description: "Digital Twin for Cross-Jurisdiction Trade Compliance",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="tradetwin-app antialiased">
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  );
}
