import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { UserContextRow, UserContextPatch } from "./types";

/**
 * The engine keeps the operator's interests and hypotheses in one Supabase
 * table. That table name is fixed by the engine, not by this app.
 */
export const USER_CONTEXT_TABLE = "user_context";

/**
 * Both values are read from the environment by name. Nothing is hardcoded and
 * no key is ever written into this repo. With either one missing the console
 * runs on sample data and says so on screen.
 */
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const isConnected = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);

let client: SupabaseClient | null = null;

function getClient(): SupabaseClient | null {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) return null;
  if (!client) {
    client = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: { persistSession: false },
    });
  }
  return client;
}

const SELECT_COLUMNS =
  "id, kind, topic, weight, stance, confidence, reasoning, specificity, status, active, created_at";

export async function fetchUserContext(): Promise<UserContextRow[]> {
  const supabase = getClient();
  if (!supabase) throw new Error("No Supabase credentials in the environment.");

  const { data, error } = await supabase
    .from(USER_CONTEXT_TABLE)
    .select(SELECT_COLUMNS)
    .order("kind", { ascending: true })
    .order("created_at", { ascending: true });

  if (error) throw new Error(error.message);
  return (data ?? []) as UserContextRow[];
}

/**
 * Writes one row and reads it straight back, so the console shows what the
 * database actually holds rather than what it hoped it wrote.
 */
export async function saveUserContextRow(
  id: string,
  patch: UserContextPatch,
): Promise<UserContextRow> {
  const supabase = getClient();
  if (!supabase) throw new Error("No Supabase credentials in the environment.");

  const { data, error } = await supabase
    .from(USER_CONTEXT_TABLE)
    .update(patch)
    .eq("id", id)
    .select(SELECT_COLUMNS)
    .single();

  if (error) throw new Error(error.message);
  if (!data) throw new Error("The row was not returned after the update.");
  return data as UserContextRow;
}
