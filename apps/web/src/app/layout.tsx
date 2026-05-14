import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { auth } from "../../auth";
import { TopNav } from "@/components/nav/top-nav";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "StockIt",
  description: "Personal portfolio-action engine",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const session = await auth();
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {session?.user ? <TopNav email={session.user.email} /> : null}
        {children}
      </body>
    </html>
  );
}
