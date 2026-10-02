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
  expert: "Экспертный", simple: "Простой", selling: "Продающий", friendly: "Дружелюбный", custom: "Свой prompt",
};
