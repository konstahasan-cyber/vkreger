export function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function fmtMoney(value: number | null | undefined): string {
  return "$" + (value ?? 0).toFixed(value && value < 1 ? 4 : 2);
}

export function toLocalInput(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export const STATUS_LABELS: Record<string, string> = {
  QUESTION: "Вопрос", LEAD: "Заявка", NEGATIVE: "Негатив", SPAM: "Спам", OTHER: "Другое", triaging: "AI разбирает",
  warning: "Предупреждение", info: "Инфо", callback: "Callback API", longpoll: "Long Poll", none: "Выключено",
  draft: "Черновик", approved: "Одобрен", scheduled: "В очереди", publishing: "Публикуется", published: "Опубликован",
  failed: "Ошибка", alive: "Alive", dead: "Dead", unknown: "Не проверен", active: "Активен", invalid: "Токен недействителен",
  error: "Ошибка", disabled: "Отключён", new: "Новый", analyzing: "Анализ", proposal_ready: "Готово preview",
  paused: "Пауза", archived: "Архив", pending: "Ожидает", running: "Выполняется", success: "Готово",
  suggested: "Предложен ответ", pending_approval: "Ждёт подтверждения", sent: "Отправлен", rejected: "Отклонён",
  ignored: "Игнор", in_progress: "В работе", won: "Успех", lost: "Потерян", planned: "Запланирован", used: "Использован",
  skipped: "Пропущен",
};

export const GOALS: Record<string, string> = {
  leads: "Лиды", sales: "Продажи", reach: "Охваты", expertise: "Экспертность", traffic: "Трафик на сайт",
};

export const TONES: Record<string, string> = {
  expert: "Экспертный", simple: "Простой", selling: "Продающий", friendly: "Дружелюбный", custom: "Свой стиль",
};

export const JOB_LABELS: Record<string, string> = {
  project_setup: "AI-анализ бизнеса", content_plan: "Контент-план", generate_posts: "Генерация постов",
  launch_community: "Запуск сообщества", brand_import: "Анализ стиля компании", design_generate: "Аватар и обложка", fill_queue: "Заполнение очереди", analyst_review: "Ревизия стратегии",
};

export const RUBRIC_LABELS: Record<string, string> = {
  educational: "Обучение", case: "Кейсы", faq: "Вопросы-ответы", product: "Продукт", sales: "Продажи",
  expert: "Экспертность", news: "Новости", engagement: "Вовлечение", pinned: "Закреп",
};

export function rubricLabel(code: string | null | undefined): string {
  if (!code) return "—";
  return RUBRIC_LABELS[code] || code;
}

export function fmtDay(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short" });
}

export function fmtTime(value: string | null | undefined): string {
  if (!value) return "";
  return new Date(value).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}
