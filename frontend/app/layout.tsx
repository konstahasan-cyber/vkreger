import type { Metadata } from "next";
import "./emoji.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "VKreger — AI-панель сообществ VK",
  description: "Создание, оформление и ведение сообществ ВКонтакте с помощью AI",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
