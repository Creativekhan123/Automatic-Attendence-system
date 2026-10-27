import { createClient } from '@supabase/supabase-js';

const DEFAULT_SUPABASE_URL = 'https://ibowhhonlxzsikgijwnl.supabase.co';
const DEFAULT_SUPABASE_KEY = 'sb_publishable_KL45K5cqhbCWHaZ_9GmTAA_g62FEdRW';

export function getSupabaseConfig() {
  const customUrl = localStorage.getItem('fleet_supabase_url');
  const customKey = localStorage.getItem('fleet_supabase_key');
  return {
    url: (customUrl && customUrl.trim()) || DEFAULT_SUPABASE_URL,
    key: (customKey && customKey.trim()) || DEFAULT_SUPABASE_KEY,
  };
}

export function saveSupabaseConfig(url, key) {
  if (url) localStorage.setItem('fleet_supabase_url', url.trim());
  if (key) localStorage.setItem('fleet_supabase_key', key.trim());
}

export function resetSupabaseConfig() {
  localStorage.removeItem('fleet_supabase_url');
  localStorage.removeItem('fleet_supabase_key');
}

export function getClient() {
  const { url, key } = getSupabaseConfig();
  return createClient(url, key, {
    auth: { persistSession: false },
  });
}

export const supabase = getClient();
