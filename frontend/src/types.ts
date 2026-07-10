export interface ModelOption {
  id:string; label:string; provider:string; description:string; token_label:string; token_provider:string;
  recommended_for:('generation'|'judge')[]; badge?:string; key_url?:string|null;
}
export type Theme = 'dark' | 'light' | 'system'
export type AccentColor = 'violet' | 'indigo' | 'blue' | 'teal' | 'emerald' | 'rose' | 'orange'
export type Direction = 'mixed' | 'term_to_definition' | 'definition_to_term'

export interface Settings {
  theme: Theme; accent_color: AccentColor; study_direction: Direction; generation_model: string; has_generation_token: boolean;
  judge_model: string; has_judge_token: boolean; token_status: Record<string, boolean>;
  judge_acceptance_score: number; reveal_threshold: number;
  daily_new_limit: number; learning_steps_minutes: number[]; relearning_steps_minutes: number[];
  graduating_interval_days: number; easy_interval_days: number; easy_bonus: number;
  hard_multiplier: number; lapse_multiplier: number; minimum_ease: number;
  term_to_definition_easy_seconds: number; term_to_definition_good_seconds: number;
  definition_to_term_easy_seconds: number; definition_to_term_good_seconds: number;
}
export interface Pool { id:number; name:string; description:string; accent:string; archived:boolean; card_count:number; due_count:number; created_at:string; updated_at:string }
export interface Schedule { state:string; due_at:string; interval_days:number; ease_factor:number; step_index:number; repetitions:number; lapses:number; last_reviewed_at:string|null }
export interface Example {sentence:string; note:string}
export interface Card {
  id:number; pool:number; pool_name:string; term:string; normalized_term:string; part_of_speech:string; ipa:string;
  short_definition:string; definition:string; examples:Example[]; forms:Record<string,string>; synonyms:string[];
  antonyms:string[]; collocations:string[]; usage_notes:string; aliases:string[]; suspended:boolean;
  schedule:Schedule; created_at:string; updated_at:string;
}
export interface JudgeResult {grading:'binary'|'ordinal'; score:number; verdict:string; feedback:string; matched_concepts:string[]; missing_or_wrong_concepts:string[]; accepted:boolean; should_reveal:boolean; review_recorded?:boolean}
export interface Overview {total_cards:number; due_now:number; new_cards:number; reviews_today:number; retention:number; streak:number; activity:{day:string;reviews:number}[]}
export interface Analytics {
  daily:{day:string;cost:number;tokens:number;calls:number}[];
  by_pool:{pool_id:number|null;pool__name:string|null;accent?:string;cost:number;tokens:number;calls:number}[];
  totals:{cost:number;tokens:number;calls:number;average_latency:number};
  failures:{id:number;operation:string;model:string;error:string;created_at:string}[];
}

export type BulkJobStatus = 'queued'|'running'|'completed'|'completed_with_errors'|'failed'|'cancelled'
export interface BulkJob {
  id:string; pool:number|null; pool_name:string; status:BulkJobStatus; batch_size:number; max_rounds:number; current_round:number;
  total_count:number; created_count:number; failed_count:number; skipped_count:number; processed_count:number; progress:number;
  failed_terms:{term:string;error:string;attempts:number}[]; error:string; started_at:string|null; finished_at:string|null; heartbeat_at:string|null; created_at:string; updated_at:string;
}
