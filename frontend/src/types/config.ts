export interface WelcomeConfig {
  is_enabled: boolean;
  greeting?: string;
  assistant_name?: string;
  description: string;
  questions?: string[];
}

export interface NextQuestionsConfig {
  is_enabled: boolean;
  count: number;
}

export interface VoiceTTSConfig {
  is_enabled: boolean;
  voice_name: string;
  speed: number;
}

export interface VoiceSTTConfig {
  is_enabled: boolean;
  engine: string;
}

export interface ModelItem {
  id: string;
  name: string;
  type?: 'llm' | 'embedding';
  provider?: string;
  base_url?: string;
  api_key?: string;
  credential_model_id?: string;
  description?: string;
  context_window?: number | null;
  max_input_tokens?: number | null;
  max_output_tokens?: number | null;
}

export interface ModelSettingConfig {
  is_enabled: boolean;
  default_model: string;
  default_embedding_model?: string;
  temperature: number;
  available_models: ModelItem[];
}

export interface FrequentQuestionsConfig {
  is_enabled: boolean;
  threshold?: number;
  reset_required?: boolean;
}

export interface AppConfigs {
  welcome_setting: WelcomeConfig;
  next_questions: NextQuestionsConfig;
  voice_tts: VoiceTTSConfig;
  voice_stt: VoiceSTTConfig;
  model_setting: ModelSettingConfig;
  frequent_questions: FrequentQuestionsConfig;
}
