export interface Job {
  id: number;
  type: string;
  status: "pending" | "running" | "success" | "failed";
  project_id: number | null;
  params: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface Proxy {
  id: number;
  scheme: string;
  host: string;
  port: number;
  username: string | null;
  password_masked: string | null;
  label: string | null;
  status: string;
  external_ip: string | null;
  country: string | null;
  country_code: string | null;
  latency_ms: number | null;
  last_checked_at: string | null;
  last_error: string | null;
  account_id: number | null;
  account_name: string | null;
}

export interface Account {
  id: number;
  name: string;
  vk_user_id: number | null;
  status: string;
  last_checked_at: string | null;
  last_error: string | null;
  proxy_id: number | null;
  proxy_display: string | null;
  proxy_status: string | null;
  auto_replace_proxy: boolean;
  info: { first_name?: string; last_name?: string; screen_name?: string; photo?: string };
  groups_cache: { id: number; name: string; screen_name?: string; members_count?: number }[];
  created_at: string;
}

export interface Rubric {
  id: number;
  code: string;
  name: string;
  description: string | null;
  weight: number;
  is_active: boolean;
}

export interface Project {
  id: number;
  name: string;
  business_name: string;
  theme: string | null;
  niche: string | null;
  city: string | null;
  target_audience: string | null;
  product_description: string | null;
  advantages: string | null;
  website: string | null;
  contacts: string | null;
  goal: string;
  posts_per_day: number | null;
  posts_per_week: number | null;
  tone: string;
  custom_tone_prompt: string | null;
  vk_account_id: number | null;
  status: string;
  timezone: string;
  posting_times: string[];
  autopilot: boolean;
  auto_approve: boolean;
  images_enabled: boolean;
  image_format: string;
  auto_reply_mode: string;
  auto_reply_types: string[];
  context_summary: string | null;
  community_id: number | null;
  community_name: string | null;
  brand: Brand;
  created_at: string;
}

export interface BrandAsset { path: string; version: number; uploaded_version?: number | null }

export interface Brand {
  community_name?: string;
  style?: {
    summary?: string; palette?: string[]; fonts?: string[]; visual_style?: string; image_style?: string;
    tone_of_voice?: string; key_phrases?: string[]; business_facts?: string[]; source?: string; logo_url?: string | null;
  };
  design?: { colors?: string[]; style?: string };
  avatar?: BrandAsset;
  cover?: BrandAsset;
}

export interface ProjectDetail extends Project {
  setup_proposal: Record<string, unknown>;
  rubrics: Rubric[];
  strategy: Record<string, unknown> | null;
  strategy_version: number | null;
}

export interface Community {
  id: number;
  vk_group_id: number;
  name: string;
  screen_name: string | null;
  description: string | null;
  members_count: number | null;
  is_admin: boolean;
  created_by_app: boolean;
  account_id: number | null;
  project_id: number | null;
  event_mode: string;
  has_community_token: boolean;
  pinned_post_id: number | null;
  last_synced_at: string | null;
  last_error: string | null;
}

export interface Post {
  id: number;
  project_id: number;
  community_id: number | null;
  title: string | null;
  text: string;
  attachments: string[];
  category: string | null;
  topic: string | null;
  cta: string | null;
  hashtags: string[];
  scheduled_at: string | null;
  published_at: string | null;
  status: string;
  vk_post_id: number | null;
  attempts: number;
  last_error: string | null;
  is_pinned: boolean;
  image_prompt: string | null;
  image_format: string;
  image_url: string | null;
  generation_metadata: Record<string, unknown>;
  analytics: Record<string, number | string>;
  created_at: string;
}

export interface PlanItem {
  id: number;
  rubric_code: string;
  topic: string;
  angle: string | null;
  planned_for: string | null;
  status: string;
  post_id: number | null;
}

export interface InboxItem {
  id: number;
  project_id: number | null;
  community_id: number;
  kind: string;
  from_id: number | null;
  text: string;
  classification: string | null;
  confidence: number | null;
  suggested_reply: string | null;
  reply_text: string | null;
  reply_status: string;
  sent_at: string | null;
  error: string | null;
  created_at: string;
}

export interface Lead {
  id: number;
  project_id: number | null;
  vk_user_id: number | null;
  name: string | null;
  contact: string | null;
  need: string | null;
  status: string;
  notes: string | null;
  created_at: string;
}

export interface SystemLog {
  id: number;
  level: string;
  source: string;
  message: string;
  project_id: number | null;
  created_at: string;
}

export interface AuditLog {
  id: number;
  user_id: number | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  details: Record<string, unknown>;
  ip: string | null;
  created_at: string;
}
