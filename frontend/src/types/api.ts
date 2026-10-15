export type User = {
  id: string;
  email: string;
  is_admin: boolean;
};

export type Email = {
  id: string;
  thread_id: string;
  sender: string;
  recipients: string[];
  subject: string;
  body_text: string;
  received_at: string;
  category: string | null;
  priority: number | null;
  summary: string | null;
  expected_action: string | null;
  needs_review: boolean;
  status: string;
};

export type EmailPage = {
  items: Email[];
  page: number;
  limit: number;
  total: number;
};

export type Thread = {
  id: string;
  subject: string;
  emails: Email[];
};

export type PriorityEmail = {
  id: string;
  thread_id: string;
  sender: string;
  subject: string;
  received_at: string;
  category: string | null;
  priority: number | null;
  reason: string;
};

export type DailySummary = {
  date: string;
  total_emails: number;
  pending_emails: number;
  replied_emails: number;
  draft_ready_emails: number;
  top_priority_emails: PriorityEmail[];
  daily_summary: string;
};
