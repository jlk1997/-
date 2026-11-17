import {
  API_BASE,
  ApiError,
  getToken,
  httpFetch,
  parseErrorDetail,
  parseResponse,
  request,
  uploadRequest,
} from "./core";
import { subscribeJobTracker, type JobPayload } from "./jobTracker";

export const api = {
  register: (
    email: string,
    username: string | undefined,
    password: string,
    referralCode?: string,
    acceptedTermsVersion?: string,
    acceptedPrivacyVersion?: string,
    otp?: string,
  ) =>
    request<{ access_token: string }>("/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        otp,
        ...(username ? { username } : {}),
        ...(referralCode ? { referral_code: referralCode } : {}),
        accepted_terms_version: acceptedTermsVersion,
        accepted_privacy_version: acceptedPrivacyVersion,
      }),
    }),
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  sendEmailOtp: (email: string, purpose: "register" | "login" | "reset" | "rebind" | "bind") =>
    request<{ ok: boolean; cooldown_seconds: number }>("/auth/email-otp", {
      method: "POST",
      body: JSON.stringify({ email, purpose }),
    }),
  changeEmail: (newEmail: string, newOtp: string, currentOtp?: string) =>
    request<{
      email: string;
      email_verified?: boolean;
      email_bound?: boolean;
    }>("/auth/change-email", {
      method: "POST",
      body: JSON.stringify({
        new_email: newEmail,
        new_otp: newOtp,
        ...(currentOtp ? { current_otp: currentOtp } : {}),
      }),
    }),
  verifyEmail: (otp: string) =>
    request<{ email: string; email_verified?: boolean }>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ otp }),
    }),
  changePassword: (password: string, opts?: { currentPassword?: string; otp?: string }) =>
    request<{ ok: boolean }>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        password,
        ...(opts?.currentPassword ? { current_password: opts.currentPassword } : {}),
        ...(opts?.otp ? { otp: opts.otp } : {}),
      }),
    }),
  loginOtp: (email: string, otp: string) =>
    request<{ access_token: string }>("/auth/login-otp", {
      method: "POST",
      body: JSON.stringify({ email, otp }),
    }),
  resetPassword: (email: string, otp: string, password: string) =>
    request<{ access_token: string }>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ email, otp, password }),
    }),
  me: () =>
    request<{
      id: string;
      username: string;
      email: string;
      display_name?: string;
      tenant_id?: string;
      is_tenant_admin?: boolean;
      is_admin?: boolean;
      deletion_scheduled_at?: string | null;
      consent_missing?: string[];
      email_verified?: boolean;
      email_bound?: boolean;
    }>("/auth/me"),
  analyzeEmotion: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return uploadRequest<{ moods: string[]; genres: string[]; arousal?: number; valence?: number }>(
      "/emotion/analyze",
      form
    );
  },
  generatePlaylist: (opts: {
    file?: File | null;
    seedWorkId?: string | null;
    textIntent?: string;
    presetId?: string | null;
    generationMode?: string;
    steps: number;
    targetCurve: string;
    instrumental?: boolean;
    title?: string;
    waypoints?: Array<{ step: number; arousal: number; valence: number; description?: string }>;
    musicParams?: { bpm_range: [number, number]; key: string; duration_preference: string };
    creativeSpec?: Record<string, unknown>;
    reference?: { work_id: string; av_offset?: { arousal: number; valence: number } };
    idempotencyKey?: string;
  }) => {
    const form = new FormData();
    if (opts.file) form.append("file", opts.file);
    if (opts.seedWorkId) form.append("seed_work_id", opts.seedWorkId);
    if (opts.textIntent) form.append("text_intent", opts.textIntent);
    if (opts.presetId) form.append("preset_id", opts.presetId);
    form.append("generation_mode", opts.generationMode || "prompt_journey");
    form.append("steps", String(opts.steps));
    form.append("target_curve", opts.targetCurve);
    form.append("instrumental", String(opts.instrumental ?? true));
    if (opts.title) form.append("title", opts.title);
    if (opts.waypoints?.length) form.append("waypoints_json", JSON.stringify(opts.waypoints));
    if (opts.reference) {
      form.append(
        "journey_json",
        JSON.stringify({
          mode: opts.generationMode || "prompt_journey",
          steps: opts.steps,
          target_curve: opts.targetCurve,
          instrumental: opts.instrumental ?? true,
          title: opts.title,
          waypoints: opts.waypoints || [],
          reference: opts.reference,
        })
      );
    }
    if (opts.musicParams) {
      form.append("bpm_min", String(opts.musicParams.bpm_range[0]));
      form.append("bpm_max", String(opts.musicParams.bpm_range[1]));
      form.append("key", opts.musicParams.key);
      form.append("duration_preference", opts.musicParams.duration_preference);
    }
    if (opts.creativeSpec) {
      form.append("creative_spec_json", JSON.stringify(opts.creativeSpec));
    }
    return uploadRequest<{ id: string; status: string; progress: number; current_step: number; total_steps: number }>(
      "/works/generate/playlist",
      form,
      { idempotencyKey: opts.idempotencyKey },
    );
  },
  getPresets: () =>
    request<
      Array<{
        id: string;
        label: string;
        category?: string;
        description?: string;
        example_intent?: string;
        member_only?: boolean;
      }>
    >("/config/presets"),
  applyPreset: (presetId: string, steps = 6, textIntent?: string) =>
    request<{
      preset_id: string;
      text_intent: string;
      moods: string[];
      genres: string[];
      journey: Record<string, unknown>;
      music_params: { bpm_range: number[]; key: string; duration_preference: string };
    }>("/studio/apply-preset", {
      method: "POST",
      body: JSON.stringify({ preset_id: presetId, steps, text_intent: textIntent }),
    }),
  getUserProfile: (username: string) =>
    request<{
      username: string;
      display_name?: string;
      bio?: string;
      avatar_url?: string;
      stats: { works: number; followers: number; following: number; live_store_total?: number; commercial_works?: number };
      is_following?: boolean | null;
      showcase?: {
        live_store_total?: number;
        live_works?: number;
        commercial_works?: number;
        featured?: Array<{ work_id: string; title?: string; cover_url?: string; live_stores?: number; commercial?: boolean }>;
      };
    }>(`/users/${username}/profile`),
  getUserWorks: (username: string) =>
    request<
      Array<{
        id: string;
        title: string;
        audio_url: string;
        hls_url?: string;
        cover_url?: string;
        moods: string[];
        post_process_status?: Record<string, unknown>;
        c2pa_verified?: boolean;
      }>
    >(`/users/${username}/works`),
  getUserPosts: (username: string) =>
    request<
      Array<{
        id: string;
        caption?: string;
        like_count: number;
        comment_count?: number;
        liked_by_me?: boolean;
        author_username?: string;
        tags?: string[];
        work?: {
          id: string;
          title: string;
          audio_url: string;
          hls_url?: string;
          cover_url?: string;
          moods?: string[];
        };
      }>
    >(`/users/${username}/posts`),
  followUser: (username: string) =>
    request<{ following: boolean }>(`/community/follow/${username}`, { method: "POST" }),
  updateProfile: (display_name?: string, bio?: string) =>
    request<{ display_name?: string; bio?: string }>("/users/me/profile", {
      method: "PUT",
      body: JSON.stringify({ display_name, bio }),
    }),
  getMyProfile: () =>
    request<{ username: string; display_name?: string; bio?: string; avatar_url?: string }>("/users/me/profile"),
  getEmotionTags: () =>
    request<{ mood_tags: string[]; genre_tags: string[] }>("/emotion/tags"),
  listCollections: () =>
    request<Array<{ id: string; work: { id: string; title: string; audio_url: string; hls_url?: string; cover_url?: string; moods: string[] }; created_at: string }>>(
      "/collections"
    ),
  getPlatformConfig: () =>
    request<{
      mock_ai?: boolean;
      mock_payment?: boolean;
      frontend_base_url?: string;
      debug?: boolean;
      farm_navigate?: boolean;
      partners_configured?: boolean;
      essentia_ready?: boolean;
      payout_mode?: string;
      kyc_provider_configured?: boolean;
      studio: {
        curves: string[];
        keys: string[];
        bpm_presets: Array<{ label: string; range: [number, number] }>;
        duration_options: Array<{ value: string; label: string }>;
        sound_recipe?: {
          instruments: Array<{ id: string; label_zh?: string; label_en?: string; token?: string }>;
          genres: Array<{ id: string; label_zh?: string; label_en?: string; token?: string }>;
          moods: Array<{ id: string; label_zh?: string; token?: string }>;
          tempo_feel: Array<{ id: string; label_zh?: string; label_en?: string }>;
          textures: Array<{ id: string; label_zh?: string; token?: string }>;
          meters: Array<{ id: string; label_zh?: string; token?: string }>;
          eras: Array<{ id: string; label_zh?: string; token?: string }>;
        };
        max_lyrics_length: number;
        default_bpm_range: [number, number];
        default_key: string;
        default_duration: string;
        lyrics_optimizer_default?: boolean;
        cover_mode_default?: string;
      };
    }>("/config/platform"),
  getFeatureFlags: () => request<Record<string, boolean>>("/config/flags"),
  cancelJob: (jobId: string) =>
    request<{ id: string; status: string }>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  pickVariationPrimary: (jobId: string, workId: string) =>
    request<{ id: string; status: string; result?: Record<string, unknown> }>(`/jobs/${jobId}/pick-variation`, {
      method: "POST",
      body: JSON.stringify({ work_id: workId }),
    }),
  planTextJourney: (textIntent: string, steps = 6) =>
    request<{ title: string; target_curve: string; steps: number; waypoints: Array<{ step: number; arousal: number; valence: number; description?: string }> }>(
      "/studio/journey/plan",
      { method: "POST", body: JSON.stringify({ text_intent: textIntent, steps }) }
    ),
  coverPreprocess: (workId: string) =>
    request<{ cover_feature_id?: string; formatted_lyrics?: string; structure_result?: unknown; audio_duration?: number }>(
      "/studio/music-cover/preprocess",
      { method: "POST", body: JSON.stringify({ work_id: workId, prompt: "preview" }) }
    ),
  getWorkRefineHints: (workId: string) =>
    request<{
      work_id: string;
      title: string;
      bpm?: number | null;
      key?: string | null;
      arousal?: number | null;
      valence?: number | null;
      moods?: string[];
      suggested_intent: string;
      sections?: Array<{ id: string; start: number; end: number }>;
      clip_windows?: Array<{ length?: number; start?: number; end?: number }>;
      human_edits?: Array<{ kind?: string; section?: string; at?: string }>;
      duration?: number | null;
      waveform_url?: string | null;
      remelt_explain?: string | null;
      stems?: { quality?: string; grade?: string; stems?: string[]; urls?: Record<string, string> };
      sku_kind?: string | null;
    }>(`/studio/works/${workId}/refine-hints`),
  recordHumanEdit: (workId: string, payload: { kind?: string; section?: string; note?: string; start?: number; end?: number }) =>
    request<{ ok: boolean }>(`/studio/works/${workId}/human-edit`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listEffectPacks: (scope = "all", surface = "h5", need?: string) =>
    request<
      Array<{
        id: string;
        slug?: string | null;
        title: string;
        description?: string | null;
        price_credits: number;
        is_official: boolean;
        status: string;
        owned?: boolean;
        author_username?: string;
        locale_titles?: Record<string, string>;
        mix_graph?: Record<string, unknown>;
        preview_url?: string | null;
        tags?: string[];
        need_tags?: string[];
        kind?: string;
        apply_count?: number;
        bounce_count?: number;
        graph_hash?: string;
      }>
    >(`/workbench/packs?scope=${encodeURIComponent(scope)}&surface=${encodeURIComponent(surface)}${need ? `&need=${encodeURIComponent(need)}` : ""}`),
  suggestEffectPacks: (workId: string, surface = "h5") =>
    request<
      Array<{
        id: string;
        slug?: string | null;
        title: string;
        description?: string | null;
        price_credits: number;
        is_official: boolean;
        owned?: boolean;
        locale_titles?: Record<string, string>;
        preview_url?: string | null;
        need_tags?: string[];
        suggested_needs?: string[];
      }>
    >(`/workbench/packs/suggest?work_id=${encodeURIComponent(workId)}&surface=${encodeURIComponent(surface)}`),
  effectPackEarnings: () =>
    request<{
      packs: Array<{ id: string; title: string; purchase_count?: number; apply_count?: number; bounce_count?: number; released_count?: number }>;
      purchase_count: number;
      apply_count: number;
      bounce_count: number;
      released_count: number;
      fiat: boolean;
    }>("/workbench/packs/earnings"),
  purchaseEffectPack: (packId: string) =>
    request<{ owned?: boolean; purchased?: boolean; pack_id: string; credits_paid: number; mix_graph?: Record<string, unknown> }>(
      `/workbench/packs/${packId}/purchase`,
      { method: "POST" },
    ),
  previewEffectPack: (packId: string) =>
    request<{ preview_url?: string; job_id?: string; ready?: boolean; baked?: boolean; official_demo?: boolean }>(
      `/workbench/packs/${packId}/preview`,
      { method: "POST" },
    ),
  openWorkbenchSession: (workId: string) =>
    request<{
      id: string;
      source_work_id: string;
      source_title?: string;
      source_audio_url?: string;
      source_cover_url?: string;
      mix_graph: {
        version: number;
        source?: { work_id?: string };
        lanes: Array<{ id: string; kind: string; gain: number; mute: boolean; pan: number; solo?: boolean; automation?: Array<{ t: number; v: number }> }>;
        nodes: Array<{ id: string; type: string; target: string; origin?: string; params?: Record<string, number | boolean | string> }>;
        clips?: Array<{
          id: string;
          lane: string;
          src: string;
          start: number;
          end: number;
          offset: number;
          fade_in: number;
          fade_out: number;
          gain: number;
          mute?: boolean;
        }>;
        regions?: Array<{
          id: string;
          start: number;
          end: number;
          label?: string;
          active_take?: string | null;
          takes?: Array<{ id: string; work_id: string; kind?: string; audio_url?: string }>;
        }>;
        need_tags?: string[];
        intensity: number;
      };
      graph_hash?: string;
      intensity: number;
      applied_pack_id?: string | null;
      applied_pack_slug?: string | null;
      edit_lanes: {
        ready?: boolean;
        urls?: Record<string, string>;
        stems?: string[];
        quality?: string;
        label?: string;
        marks?: Array<{ tag?: string; start?: number; end?: number; estimated?: boolean }>;
        not_review_stems?: boolean;
        not_store_tracks?: boolean;
        copied_from_review?: boolean;
      };
      last_render_job_id?: string | null;
      last_result_work_id?: string | null;
      last_result_audio_url?: string | null;
      last_result_title?: string | null;
      previous_result_work_id?: string | null;
      previous_result_audio_url?: string | null;
      previous_result_title?: string | null;
      can_undo?: boolean;
      has_clips?: boolean;
      desktop_edits?: boolean;
      lane_pack_degraded?: boolean;
      source_hls_url?: string | null;
      source_waveform_url?: string | null;
      source_duration?: number | null;
      source_moods?: string[];
      source_release_status?: string | null;
      last_result_release_status?: string | null;
      last_result_cover_url?: string | null;
      continued_from_result?: boolean;
      next_action?: {
        door?: "beautify" | "radio" | "release" | "deliveries" | "fix";
        work_id?: string | null;
        title?: string | null;
        release_status?: string | null;
        qc_ready?: boolean;
        from_workbench?: boolean;
        degraded?: boolean;
        cover_url?: string | null;
      };
      credit_estimate?: {
        bounce?: number;
        regen?: number;
        ai?: number;
        credits?: number;
        ledger?: string;
        fiat?: boolean;
      };
      preview_url?: string | null;
    }>("/workbench/sessions", { method: "POST", body: JSON.stringify({ work_id: workId }) }),
  getWorkbenchSession: (sessionId: string) =>
    request<Record<string, unknown>>(`/workbench/sessions/${sessionId}`),
  patchWorkbenchSession: (
    sessionId: string,
    payload: { mix_graph?: Record<string, unknown>; intensity?: number; lanes?: Array<Record<string, unknown>> },
  ) => request<Record<string, unknown>>(`/workbench/sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  applyEffectPack: (sessionId: string, packId: string, intensity = 1) =>
    request<Record<string, unknown>>(`/workbench/sessions/${sessionId}/apply-pack`, {
      method: "POST",
      body: JSON.stringify({ pack_id: packId, intensity }),
    }),
  renderWorkbench: (sessionId: string) =>
    request<{ job_id: string; session_id: string; graph_hash: string }>(`/workbench/sessions/${sessionId}/render`, { method: "POST" }),
  bounceWorkbench: (sessionId: string, file: Blob, title: string) => {
    const form = new FormData();
    form.append("file", file, "bounce.wav");
    form.append("title", title);
    return uploadRequest<{
      work_id: string;
      title: string;
      audio_url: string;
      wav_url?: string | null;
      parent_work_id: string;
      loudness?: Record<string, unknown>;
      tracks: number;
    }>(`/workbench/sessions/${sessionId}/bounce`, form);
  },
  separateWorkbenchLanes: (sessionId: string, profile = "full") =>
    request<{ job_id?: string; ready?: boolean; copied_from_review?: boolean; session?: Record<string, unknown> }>(
      `/workbench/sessions/${sessionId}/lanes?profile=${profile === "vocals2" ? "vocals2" : "full"}`,
      { method: "POST" },
    ),
  publishEffectPack: (
    sessionId: string,
    payload: { title: string; description?: string; price_credits?: number; need_tags?: string[]; kind?: string },
    surface = "h5",
  ) =>
    request<{ id: string; status: string; title: string }>(
      `/workbench/sessions/${sessionId}/publish-pack?surface=${encodeURIComponent(surface)}`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  publishEffectPackPreflight: (sessionId: string) =>
    request<{ ok: boolean; has_clips: boolean; stripped_clips: boolean; kind: string; forbids_external_audio?: boolean }>(
      `/workbench/sessions/${sessionId}/publish-preflight`,
    ),
  undoWorkbenchSession: (sessionId: string) => request<Record<string, unknown>>(`/workbench/sessions/${sessionId}/undo`, { method: "POST" }),
  trimWorkbenchSession: (sessionId: string, start: number, end: number) =>
    request<Record<string, unknown>>(`/workbench/sessions/${sessionId}/trim`, {
      method: "POST",
      body: JSON.stringify({ start, end }),
    }),
  activateWorkbenchTake: (sessionId: string, regionId: string, takeId: string) =>
    request<Record<string, unknown>>(`/workbench/sessions/${sessionId}/takes`, {
      method: "POST",
      body: JSON.stringify({ region_id: regionId, take_id: takeId }),
    }),
  listPackDemands: (scope = "open") =>
    request<
      Array<{
        id: string;
        work_id: string;
        work_title?: string;
        brief: string;
        need_tags?: string[];
        bid_credits: number;
        status: string;
        claimed_by_id?: string | null;
        pack_id?: string | null;
      }>
    >(`/workbench/demands?scope=${encodeURIComponent(scope)}`),
  createPackDemand: (payload: { work_id: string; brief: string; need_tags?: string[]; bid_credits?: number; reference_work_id?: string }) =>
    request<{ id: string; status: string }>(`/workbench/demands`, { method: "POST", body: JSON.stringify(payload) }),
  claimPackDemand: (demandId: string) =>
    request<{ id: string; status: string; work_id: string }>(`/workbench/demands/${demandId}/claim`, { method: "POST" }),
  deliverPackDemand: (demandId: string, payload: { pack_id?: string; session_id?: string }) =>
    request<{ id: string; status: string }>(`/workbench/demands/${demandId}/deliver`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  reviewEffectPack: (packId: string, status: "published" | "rejected") =>
    request<{ id: string; status: string }>(`/workbench/admin/packs/${packId}/review`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  listPendingEffectPacks: () =>
    request<
      Array<{ id: string; title: string; description?: string | null; price_credits: number; author_username?: string; status: string }>
    >("/workbench/admin/packs"),
  syncWorkbenchFromLight: (payload: { work_id: string; semitones?: number; tempo?: number; master?: boolean }) =>
    request<Record<string, unknown>>("/workbench/sessions/from-light", { method: "POST", body: JSON.stringify(payload) }),
  estimateWorkbenchSession: (sessionId: string) =>
    request<{ bounce?: number; regen?: number; ai?: number; credits?: number; ledger?: string; fiat?: boolean }>(
      `/workbench/sessions/${sessionId}/estimate`,
    ),
  regenWorkbench: (
    sessionId: string,
    kind: "extend" | "remelt" | "same_style",
    seconds = 15,
    region?: { start?: number; end?: number; id?: string },
  ) =>
    request<{ job_id: string; session_id: string; kind: string; credits: number }>(`/workbench/sessions/${sessionId}/regen`, {
      method: "POST",
      body: JSON.stringify({
        kind,
        seconds,
        region_start: region?.start,
        region_end: region?.end,
        region_id: region?.id,
      }),
    }),
  transformWork: (workId: string, payload: { semitones?: number; tempo?: number }) =>
    request<{ ok: boolean; audio_url?: string; preflight?: { passed?: boolean } }>(`/studio/works/${workId}/transform`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  masterWork: (workId: string) =>
    request<{ ok: boolean; audio_url?: string; preflight?: { passed?: boolean } }>(`/studio/works/${workId}/master`, {
      method: "POST",
    }),
  undoWorkEdit: (workId: string) =>
    request<{ ok: boolean; audio_url?: string }>(`/studio/works/${workId}/undo-edit`, { method: "POST" }),
  extendWork: (workId: string, duration: 15 | 30 = 15) =>
    request<{ job_id: string; work_id?: string }>(`/studio/works/${workId}/extend`, {
      method: "POST",
      body: JSON.stringify({ duration }),
    }),
  spawnInstrumentalSku: (workId: string) =>
    request<{ work_id: string; parent_work_id: string; title: string; sku: string; audio_url?: string }>(
      `/studio/works/${workId}/instrumental-sku`,
      { method: "POST" },
    ),
  getJob: (id: string) =>
    request<{
      id: string;
      status: string;
      progress: number;
      current_step: number;
      total_steps: number;
      phase?: string | null;
      job_type?: string | null;
      remix_source?: { work_id: string; remix_intent?: string | null; output_title?: string | null } | null;
      result?: {
        work_id?: string;
        audio_url?: string;
        title?: string;
        cover_url?: string;
        hls_url?: string;
        playlist_id?: string;
        work_ids?: string[];
        completed_steps?: Array<{ work_id: string; step: number; audio_url?: string; title?: string }>;
      };
      error_message?: string;
      status_message?: string;
    }>(`/jobs/${id}`),
  getActiveJob: () =>
    request<{
      id: string;
      status: string;
      progress: number;
      current_step: number;
      total_steps: number;
      phase?: string | null;
      job_type?: string | null;
      remix_source?: { work_id: string; remix_intent?: string | null; output_title?: string | null } | null;
      result?: Record<string, unknown>;
      error_message?: string;
      status_message?: string;
    } | null>(`/jobs/active`),
  listWorks: (sort = "newest", mood?: string, limit?: number) =>
    request<
      Array<{
        id: string;
        title: string;
        audio_url: string;
        hls_url?: string;
        cover_url?: string;
        moods: string[];
        parent_work_id?: string;
        post_process_status?: Record<string, unknown>;
        from_workbench?: boolean;
        superseded_by_work_id?: string | null;
        c2pa_verified?: boolean;
        visibility?: string;
        version?: number;
      }>
    >(
      `/works?sort=${sort}${mood ? `&mood=${encodeURIComponent(mood)}` : ""}${
        limit != null ? `&limit=${encodeURIComponent(String(limit))}` : ""
      }`,
    ),
  getWork: (workId: string) =>
    request<{
      id: string;
      title: string;
      audio_url: string;
      hls_url?: string;
      cover_url?: string;
      moods: string[];
      allow_remix?: boolean;
      license?: string;
      version?: number;
      lyrics?: string;
      lyrics_timeline?: Array<{ time: number; text: string }>;
      release_status?: string;
      artist_name?: string;
      owner_username?: string;
      post_process_status?: Record<string, unknown>;
      from_workbench?: boolean;
      superseded_by_work_id?: string | null;
      c2pa_verified?: boolean;
      is_owner?: boolean;
    }>(`/works/${workId}`),
  getWorkQuality: (workId: string) =>
    request<{
      resonance: number;
      completion: number;
      suggestion_key: "mood" | "structure" | "publish" | "loudness" | "duration" | "originality" | "cover";
      preflight?: {
        passed?: boolean;
        duration_ok?: boolean;
        loudness_ok?: boolean;
        has_cover?: boolean;
        originality_risk?: number;
      };
      remelt_explain?: string;
      remelt_too_close?: boolean;
      remelt_distance?: number | null;
      reference_ready?: boolean;
      release_assets?: {
        master_ready?: boolean;
        master_wav?: boolean;
        stems_quality?: string;
        evidence_ready?: boolean;
        sku_kind?: string;
      };
    }>(
      `/works/${workId}/quality`
    ),
  getMoodVisual: (workId: string) =>
    request<{
      work_id: string;
      title: string;
      audio_url: string;
      cover_url?: string;
      slides: Array<Record<string, unknown>>;
      total_duration_sec: number;
    }>(`/studio/works/${workId}/mood-visual`),
  exportMoodVisual: (workId: string) =>
    request<{ id: string; export_type: string; download_url: string; cost: number; meta: Record<string, unknown> }>(
      `/studio/works/${workId}/mood-visual/export`,
      { method: "POST" }
    ),
  updateWork: (
    workId: string,
    payload: { title?: string; expectedVersion?: number; syncCommunityCaption?: boolean | null },
  ) =>
    request<{ id: string; title: string; version: number; post_caption_synced?: boolean }>(`/works/${workId}`, {
      method: "PATCH",
      headers:
        payload.expectedVersion != null ? { "If-Match": String(payload.expectedVersion) } : undefined,
      body: JSON.stringify({
        title: payload.title,
        expected_version: payload.expectedVersion,
        sync_community_caption: payload.syncCommunityCaption,
      }),
    }),
  getFeed: (sort = "personalized", tag?: string) => {
    const params = new URLSearchParams({ sort });
    if (tag) params.set("tag", tag);
    return request<
      Array<{
        id: string;
        caption?: string;
        like_count: number;
        comment_count: number;
        liked_by_me?: boolean;
        author_is_following?: boolean;
        collected_by_me?: boolean;
        author_username: string;
        author_creator_level?: string;
        tags?: string[];
        work?: {
          id: string;
          audio_url: string;
          hls_url?: string;
          cover_url?: string;
          title: string;
          moods: string[];
          allow_remix?: boolean;
          license?: string;
          post_process_status?: Record<string, unknown>;
          c2pa_verified?: boolean;
        };
      }>
    >(`/community/feed?${params.toString()}`);
  },
  listSameStyleWall: (limit = 6) =>
    request<{
      works: Array<{
        id: string;
        title: string;
        cover_url?: string;
        audio_url?: string;
        moods?: string[];
        genres?: string[];
        owner_username?: string;
      }>;
    }>(`/community/same-style-wall?limit=${limit}`),
  listSimilarWorks: (workId: string, limit = 6) =>
    request<{
      works: Array<{
        id: string;
        title: string;
        cover_url?: string;
        audio_url?: string;
        moods?: string[];
        genres?: string[];
        owner_username?: string;
      }>;
    }>(`/works/${workId}/similar?limit=${limit}`),
  publishRecipeFromWork: (workId: string, title?: string, priceCredits = 0) =>
    request<{ id: string; title: string; price_credits: number }>(`/ecosystem/works/${workId}/recipe`, {
      method: "POST",
      body: JSON.stringify({ title, price_credits: priceCredits }),
    }),
  getRisingCreators: (limit = 5) =>
    request<
      Array<{
        username: string;
        display_name: string;
        avatar_url?: string;
        posts_count: number;
        creator_level: string;
      }>
    >(`/community/rising-creators?limit=${limit}`),
  getChallenges: () =>
    request<
      Array<{
        id: string;
        slug: string;
        title: string;
        description?: string;
        hashtag: string;
        target_curve?: string;
        cover_url?: string;
        ends_at?: string | null;
        participant_count: number;
        prize_pool_credits?: number;
      }>
    >("/challenges"),
  getChallengeLeaderboard: (slug: string, limit = 20) =>
    request<{ slug: string; title: string; entries: Array<{ rank: number; work_id: string; title: string; author: string; like_count: number; cover_url?: string }> }>(
      `/challenges/${slug}/leaderboard?limit=${limit}`
    ),
  getCreatorStats: () =>
    request<{
      works_total: number;
      published: number;
      remix_derivatives: number;
      remixes_received: number;
      total_likes: number;
      likes_7d: number;
      completed_jobs: number;
      challenge_entries: number;
      followers: number;
    }>("/users/me/creator-stats"),
  getChallenge: (slug: string) =>
    request<{
      slug: string;
      title: string;
      description?: string;
      hashtag: string;
      target_curve?: string;
      cover_url?: string;
      ends_at?: string | null;
      participant_count: number;
      entries: Array<{
        work_id: string;
        title: string;
        author: string;
        moods?: string[];
        audio_url?: string;
        hls_url?: string;
        cover_url?: string;
        like_count?: number;
      }>;
    }>(`/challenges/${slug}`),
  enterChallenge: (slug: string, workId: string, caption?: string) =>
    request<{
      entry_id: string;
      post_id: string;
      task_reward?: { task_key: string; credits_granted: number; balance: number; duplicate?: boolean } | null;
    }>(`/challenges/${slug}/enter`, {
      method: "POST",
      body: JSON.stringify({ work_id: workId, caption }),
    }),
  planCustomJourney: (
    waypoints: Array<{ step: number; arousal: number; valence: number; description?: string }>,
    title: string
  ) =>
    request<{ journey: Record<string, unknown>; music_params: Record<string, unknown> }>("/studio/journey/custom", {
      method: "POST",
      body: JSON.stringify({ title, waypoints, instrumental: true }),
    }),
  musicCover: (
    workId: string,
    prompt: string,
    options?: { cover_mode?: "one_step" | "two_step"; modified_lyrics?: string; style_lock?: boolean; idempotencyKey?: string },
  ) =>
    request<{ job_id: string }>("/studio/music-cover", {
      method: "POST",
      idempotencyKey: options?.idempotencyKey,
      body: JSON.stringify({
        work_id: workId,
        prompt,
        cover_mode: options?.cover_mode || "one_step",
        modified_lyrics: options?.modified_lyrics,
        style_lock: options?.style_lock,
      }),
    }),
  adminStats: () => request<Record<string, unknown>>("/admin/stats"),
  adminCommercial: () =>
    request<{
      billing_30d: {
        revenue_yuan: number;
        paid_orders: number;
        period_days: number;
        mrr_yuan?: number;
        ltv_estimate_yuan?: number;
        churned_subscriptions?: number;
        active_subscriptions?: number;
        new_subscriptions?: number;
      };
      pack_distribution: Record<string, number>;
      credit_grants_by_source: Record<string, number>;
      total_credits_spent: number;
      users: number;
      conversion_funnel_30d: Record<string, number>;
    }>("/admin/commercial"),
  adminActivationFunnel: (days = 30) =>
    request<{
      period_days: number;
      new_registrations: number;
      preset_selected: number;
      first_generate_start: number;
      first_generate_complete: number;
      first_listen: number;
      first_publish: number;
    }>(`/admin/activation-funnel?days=${days}`),
  adminAuditLogs: (limit = 50) =>
    request<Array<{ id: string; admin_id: string; action: string; target?: string; detail: Record<string, unknown>; created_at?: string }>>(
      `/admin/audit-logs?limit=${limit}`
    ),
  adminUsage: () =>
    request<
      Array<{
        provider: string;
        model: string;
        endpoint: string;
        tokens_used: number;
        created_at: string | null;
      }>
    >("/admin/usage"),
  adminReports: () =>
    request<
      Array<{
        id: string;
        reason: string;
        status: string;
        post_id?: string | null;
        work_id?: string | null;
        comment_id?: string | null;
        comment_preview?: string | null;
      }>
    >("/admin/reports"),
  adminResolveReport: (id: string, action?: "hide_post" | "hide_comment" | "dismiss" | "ban_user") =>
    request(`/admin/reports/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ status: "resolved", action: action || null }),
    }),
  adminFlags: () => request<Array<{ key: string; enabled: boolean; description?: string }>>("/admin/flags"),
  adminToggleFlag: (key: string, enabled: boolean) =>
    request(`/admin/flags/${key}`, { method: "PUT", body: JSON.stringify({ enabled }) }),
  adminVendorKeys: () =>
    request<{
      keys: Array<{
        id: string;
        vendor: string;
        capability: string;
        key_prefix: string;
        model?: string | null;
        enabled: boolean;
        last_error?: string | null;
        weight?: number;
      }>;
    }>("/admin/vendor-keys"),
  adminCreateVendorKey: (payload: {
    vendor: string;
    capability: string;
    api_key: string;
    base_url?: string;
    model?: string;
    weight?: number;
  }) => request("/admin/vendor-keys", { method: "POST", body: JSON.stringify(payload) }),
  adminPatchVendorKey: (id: string, payload: { enabled?: boolean; weight?: number }) =>
    request(`/admin/vendor-keys/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  adminProbeVendorKey: (id: string) =>
    request<{
      id: string;
      last_error?: string | null;
      probe?: { ok?: boolean; checked?: string; error?: string };
    }>(`/admin/vendor-keys/${id}/probe`, { method: "POST" }),
  adminGrantCredits: (payload: { email?: string; user_id?: string; amount: number }) =>
    request<{ user_id: string; username: string; email: string; balance: number; granted: number }>(
      "/admin/credits/grant",
      { method: "POST", body: JSON.stringify(payload) }
    ),
  createPost: (
    workId: string,
    caption?: string,
    opts?: { allow_remix?: boolean; license?: string; content_compliance_acknowledged?: boolean }
  ) =>
    request<{
      id: string;
      credits_balance?: number;
      task_reward?: { credits_granted?: number; balance?: number; duplicate?: boolean } | null;
    }>("/community/posts", {
      method: "POST",
      body: JSON.stringify({
        work_id: workId,
        caption,
        visibility: "public",
        tags: [],
        allow_remix: opts?.allow_remix ?? true,
        license: opts?.license ?? "allow_remix",
        content_compliance_acknowledged: opts?.content_compliance_acknowledged ?? false,
      }),
    }),
  deletePost: (postId: string) =>
    request<{ deleted: boolean }>(`/community/posts/${postId}`, { method: "DELETE" }),
  getDerivatives: (workId: string) =>
    request<
      Array<{
        id: string;
        title: string;
        audio_url: string;
        cover_url?: string;
        moods: string[];
        parent_work_id?: string;
      }>
    >(`/works/${workId}/derivatives`),
  likePost: (postId: string) =>
    request<{ like_count: number; liked: boolean }>(`/community/posts/${postId}/like`, { method: "POST" }),
  listComments: (postId: string) =>
    request<Array<{ id: string; user_id: string; username: string; content: string; created_at: string }>>(
      `/community/posts/${postId}/comments`
    ),
  addComment: (postId: string, content: string, parentId?: string) =>
    request<{ id: string; user_id: string; username: string; content: string; parent_id?: string | null; is_filtered?: boolean; created_at: string }>(
      `/community/posts/${postId}/comments`,
      { method: "POST", body: JSON.stringify({ content, parent_id: parentId }) }
    ),
  deleteComment: (postId: string, commentId: string) =>
    request<{ deleted: boolean }>(`/community/posts/${postId}/comments/${commentId}`, { method: "DELETE" }),
  remix: (workId: string, remixIntent: string, opts?: { title?: string; idempotencyKey?: string }) =>
    request<{
      job_id: string;
      credits_balance?: number;
      task_reward?: { task_key: string; credits_granted: number; balance: number; duplicate?: boolean } | null;
    }>(`/community/remix/${workId}`, {
      method: "POST",
      idempotencyKey: opts?.idempotencyKey,
      body: JSON.stringify({
        remix_intent: remixIntent,
        ...(opts?.title?.trim() ? { title: opts.title.trim().slice(0, 60) } : {}),
      }),
    }),
  getProvenance: (workId: string) =>
    request<{
      work_id: string;
      lineage: Array<Record<string, unknown>>;
      pipeline_version: string;
      human_edits?: Array<{ kind?: string; section?: string; note?: string; at?: string }>;
    }>(`/provenance/${workId}`),
  exportProvenance: async (workId: string, format = "vibe") => {
    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await httpFetch(
      `${API_BASE}/provenance/${workId}/export?format=${encodeURIComponent(format)}`,
      { headers }
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(parseErrorDetail(body, res.status), res.status);
    }
    if (!res.blob) throw new ApiError("Blob not supported", 500);
    return res.blob();
  },
  generatePlaylistBody: (payload: Record<string, unknown>, idempotencyKey?: string) =>
    request<{ id: string; status: string }>("/works/generate/playlist/body", {
      method: "POST",
      idempotencyKey,
      body: JSON.stringify(payload),
    }),
  wechatLogin: (
    code: string,
    acceptedTermsVersion?: string,
    acceptedPrivacyVersion?: string,
    referralCode?: string,
  ) =>
    request<{ access_token: string; token_type: string; user_id: string }>("/auth/wechat/login", {
      method: "POST",
      body: JSON.stringify({
        code,
        accepted_terms_version: acceptedTermsVersion,
        accepted_privacy_version: acceptedPrivacyVersion,
        ...(referralCode ? { referral_code: referralCode } : {}),
      }),
    }),
  generateLyrics: (theme: string, moods: string[] = [], language = "zh") =>
    request<{ lyrics: string; style_tags?: string | null; song_title?: string | null }>(
      "/studio/lyrics/generate",
      {
      method: "POST",
      body: JSON.stringify({ theme, moods, language }),
    }),
  polishIntent: (textIntent: string) =>
    request<{ text_intent: string }>("/studio/intent/polish", {
      method: "POST",
      body: JSON.stringify({ text_intent: textIntent }),
    }),
  parseMusicIntent: (textIntent: string, language = "zh") =>
    request<{
      creative_spec: {
        instruments: string[];
        genres: string[];
        moods: string[];
        tempo_feel: string;
        bpm?: number | null;
        bpm_range?: [number, number] | null;
        key: string;
        texture: string;
        meter: string;
        era: string;
        text_intent: string;
        style_tags: string;
      };
      preview_prompt: string;
    }>("/studio/intent/parse", {
      method: "POST",
      body: JSON.stringify({ text_intent: textIntent, language }),
    }),
  previewMusicPrompt: (payload: {
    creative_spec?: Record<string, unknown>;
    text_intent?: string;
    style_tags?: string;
    moods?: string[];
    genres?: string[];
    bpm?: number;
    key?: string;
  }) =>
    request<{ creative_spec: Record<string, unknown>; preview_prompt: string }>("/studio/prompt/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getSoundRecipeOptions: () =>
    request<{
      instruments: Array<{ id: string; label_zh?: string; label_en?: string; token?: string }>;
      genres: Array<{ id: string; label_zh?: string; label_en?: string; token?: string }>;
      moods: Array<{ id: string; label_zh?: string; token?: string }>;
      tempo_feel: Array<{ id: string; label_zh?: string; label_en?: string }>;
      textures: Array<{ id: string; label_zh?: string; token?: string }>;
      meters: Array<{ id: string; label_zh?: string; token?: string }>;
      eras: Array<{ id: string; label_zh?: string; token?: string }>;
    }>("/studio/sound-recipe/options"),
  generateSingle: (payload: {
    text_intent?: string;
    seed_work_id?: string;
    instrumental?: boolean;
    title?: string;
    lyrics?: string;
    style_tags?: string;
    song_title?: string;
    lyrics_optimizer?: boolean;
    creative_spec?: Record<string, unknown>;
    bpm?: number;
    key?: string;
    moods?: string[];
    genres?: string[];
    seed?: number;
    reference?: { work_id: string; av_offset?: { arousal?: number; valence?: number } };
    preview_pick_count?: number;
    mode?: string;
    freedom?: string;
    quality?: string;
    quick?: boolean;
    vocal?: { vocal_gender?: string; vocal_style?: string; language?: string };
    idempotencyKey?: string;
  }) =>
    request<{ id: string; status: string; job_type?: string }>("/works/generate/single", {
      method: "POST",
      idempotencyKey: payload.idempotencyKey,
      body: JSON.stringify(payload),
    }),
  listPlaylists: () => request<Array<{ id: string; title: string; track_count: number }>>("/playlists"),
  listPlaylistSubscriptions: () =>
    request<
      Array<{
        id: string;
        title: string;
        owner_username?: string;
        track_count: number;
        visibility: string;
        subscribed_at?: string | null;
      }>
    >("/playlists/subscriptions"),
  subscribePlaylist: (playlistId: string) =>
    request<{ subscribed: boolean; playlist_id: string }>(`/playlists/${playlistId}/subscribe`, { method: "POST" }),
  unsubscribePlaylist: (playlistId: string) =>
    request<{ subscribed: boolean }>(`/playlists/${playlistId}/subscribe`, { method: "DELETE" }),
  getPlaylist: (id: string) =>
    request<{
      id: string;
      title: string;
      visibility?: string;
      share_text?: string;
      tracks: Array<{
        position: number;
        shift_stage?: string;
        work: { id: string; title: string; audio_url: string; hls_url?: string; cover_url?: string; moods?: string[] };
      }>;
    }>(`/playlists/${id}`),
  publishPlaylist: (id: string, visibility: "public" | "private" | "unlisted") =>
    request<{ id: string; title: string; visibility: string }>(`/playlists/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ visibility }),
    }),
  getPublicPlaylist: (id: string) =>
    request<{
      id: string;
      title: string;
      visibility: string;
      share_text?: string;
      tracks: Array<{ position: number; shift_stage?: string; work: { id: string; title: string } }>;
    }>(`/playlists/${id}/public`),
  collectWork: (workId: string) => request<{ collected: boolean }>(`/collections/${workId}`, { method: "POST" }),
  removeCollection: (workId: string) =>
    request<{ collected: boolean }>(`/collections/${workId}`, { method: "DELETE" }),
  triggerPostProcess: (workId: string) =>
    request<{ status: string }>(`/studio/works/${workId}/post-process`, { method: "POST" }),
  reprocessWork: (workId: string) =>
    request<{ reprocessing: boolean }>(`/works/${workId}/reprocess`, { method: "POST" }),
  getWorkTimeline: (workId: string) =>
    request<{
      work_id?: string;
      title?: string;
      error?: string;
      current_stage?: string;
      next_action?: { action?: string; label?: string; priority?: number };
      stages?: Array<{
        stage: string;
        label: string;
        status: string;
        can_rerun?: boolean;
        deliveries?: Array<{ channel_code?: string; status?: string; tier?: string; store_url?: string }>;
        total_revenue_minor?: number;
        currency?: string;
      }>;
    }>(`/works/${workId}/timeline`),
  adminOpsDashboard: () =>
    request<{
      timestamp?: string;
      total_actionable?: number;
      actionable?: {
        unmatched_claims?: number;
        selector_broke?: number;
        login_wall_seats?: number;
        sla_overdue?: number;
        pending_payouts?: number;
        pending_kyc?: number;
        settlement_drafts?: number;
        pending_invoices?: number;
      };
      delivery_queue?: Record<string, number>;
      friday_queue?: {
        settlement_drafts?: number;
        pending_invoices?: number;
        pending_kyc?: number;
        pending_payouts?: number;
        auto_payout?: boolean;
      };
      friday_total?: number;
    }>("/admin/ops/dashboard"),
  adminOpsBatch: (action: string, ids: string[]) =>
    request<{ action: string; processed: number }>("/admin/ops/batch", {
      method: "POST",
      body: JSON.stringify({ action, ids }),
    }),
  submitPlaylistFeedback: (
    playlistId: string,
    body: { mood_before: number; mood_after: number; felt_shift?: boolean; note?: string },
  ) =>
    request<{ id: string }>(`/playlists/${playlistId}/feedback`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getPlaylistFeedback: (playlistId: string) =>
    request<{ mood_before: number; mood_after: number; felt_shift?: boolean; note?: string } | null>(
      `/playlists/${playlistId}/feedback`,
    ),
  trackEvent: (event: string, payload?: Record<string, unknown>) =>
    request<{ ok: boolean }>("/analytics/events", {
      method: "POST",
      body: JSON.stringify({ event, payload: payload || {} }),
    }).catch(() => ({ ok: false })),
  trackActivationEvent: (event: string, payload?: Record<string, unknown>) =>
    request<{ ok: boolean; already_tracked?: boolean }>("/analytics/activation", {
      method: "POST",
      body: JSON.stringify({ event, payload: payload || {} }),
    }).catch(() => ({ ok: false })),
  createSubscriptionCheckout: () =>
    request<{ mode: string; url?: string; credits_granted?: number; balance?: number }>(
      "/billing/subscribe",
      { method: "POST" }
    ),
  getSubscription: () =>
    request<{
      tier: string;
      status: string;
      plan_id?: string | null;
      channel?: string | null;
      monthly_credits: number;
      renews_at: string | null;
      cancel_at_period_end?: boolean;
      days_remaining?: number | null;
      perks?: { priority_queue: boolean; exclusive_presets: boolean };
      can_manage_stripe?: boolean;
    }>("/billing/subscription"),
  cancelSubscription: (immediate = false) =>
    request<{ cancelled: boolean; subscription: Record<string, unknown> }>("/billing/subscription/cancel", {
      method: "POST",
      body: JSON.stringify({ immediate }),
    }),
  getBillingPortal: () => request<{ url?: string }>("/billing/portal"),
  getPreferences: () =>
    request<{
      mood_tags: string[];
      genre_tags: string[];
      notify?: { in_app?: boolean; wechat?: boolean; email?: boolean; recall?: boolean };
    }>("/users/me/preferences"),
  updatePreferences: (
    mood_tags: string[],
    genre_tags: string[],
    notify?: { in_app?: boolean; wechat?: boolean; email?: boolean; recall?: boolean },
  ) =>
    request("/users/me/preferences", {
      method: "PUT",
      body: JSON.stringify({ mood_tags, genre_tags, ...(notify ? { notify } : {}) }),
    }),
  pollJob: (
    jobId: string,
    onUpdate: (data: { status: string; progress: number; error_message?: string }) => void,
    intervalMs = 2000
  ) => {
    let stopped = false;
    let delay = Math.min(intervalMs, 800);
    const tick = async () => {
      if (stopped) return;
      try {
        const data = await request<{ status: string; progress: number; error_message?: string }>(`/jobs/${jobId}`);
        onUpdate(data);
        if (data.status === "completed" || data.status === "failed" || data.status === "cancelled") return;
        delay = Math.min(delay * 1.5, 4000);
      } catch {
        delay = Math.min(delay * 1.5, 4000);
      }
      setTimeout(tick, delay);
    };
    tick();
    return () => {
      stopped = true;
    };
  },
  watchJob: async (jobId: string, onUpdate: (data: Record<string, unknown>) => void) => {
    try {
      const { ticket } = await request<{ ticket: string }>(`/jobs/${jobId}/stream-ticket`, { method: "POST" });
      const wsUrl =
        API_BASE.replace(/^http/, "ws") + `/jobs/${jobId}/stream?ticket=${encodeURIComponent(ticket)}`;
      const ws = new WebSocket(wsUrl);
      ws.onmessage = (ev) => onUpdate(JSON.parse(ev.data) as Record<string, unknown>);
      ws.onerror = () => ws.close();
      return ws;
    } catch {
      return null;
    }
  },
  trackJob: (
    jobId: string,
    onUpdate: (data: {
      status: string;
      progress: number;
      current_step?: number;
      total_steps?: number;
      phase?: string | null;
      job_type?: string | null;
      remix_source?: { work_id: string; remix_intent?: string | null; output_title?: string | null } | null;
      result?: Record<string, unknown>;
      error_message?: string;
      status_message?: string;
    }) => void
  ) => subscribeJobTracker(jobId, onUpdate as (data: JobPayload) => void),
  verifyProvenance: (workId: string) =>
    request<{
      verified: boolean;
      content_hash?: string;
      signature?: string;
      c2pa_manifest?: Record<string, unknown>;
      blockchain_tx_hash?: string;
    }>(`/provenance/${workId}/verify`),
  reportPost: (postId: string, reason: string) =>
    request("/community/report", { method: "POST", body: JSON.stringify({ post_id: postId, reason }) }),
  reportComment: (commentId: string, reason: string) =>
    request("/community/report", { method: "POST", body: JSON.stringify({ comment_id: commentId, reason }) }),
  previewRemix: (workId: string, remixIntent: string) =>
    request<{ original_prompt?: string; prompt?: string; bpm?: number; key?: string }>("/studio/remix/preview", {
      method: "POST",
      body: JSON.stringify({ work_id: workId, remix_intent: remixIntent }),
    }),
  getRemixTree: (workId: string) =>
    request<{
      id: string;
      title: string;
      author?: string;
      children?: Array<{ id: string; title: string; author?: string; moods?: string[]; children?: unknown[] }>;
      ancestors?: Array<{ id: string; title: string; author?: string }>;
    }>(`/works/${workId}/remix-tree`),
  getNotifications: () =>
    request<{
      unread_count: number;
      items: Array<{ id: string; type: string; payload: Record<string, unknown>; read: boolean; created_at?: string }>;
    }>("/notifications"),
  getNotificationUnread: () => request<{ unread_count: number }>("/notifications/unread"),
  markNotificationsRead: (opts: { notification_id?: string; all?: boolean }) =>
    request<{ marked: number }>("/notifications/read", { method: "POST", body: JSON.stringify(opts) }),
  copilotChat: (message: string, sessionId?: string) =>
    request<{
      session_id: string;
      reply: string;
      tool_result?: Record<string, unknown>;
      tool_name?: string;
      actions?: Array<Record<string, unknown>>;
      messages: Array<{ role: string; content: string; tool_result?: Record<string, unknown> }>;
    }>("/copilot/chat", {
      method: "POST",
      body: JSON.stringify({ message, session_id: sessionId }),
    }),
  copilotChatStream: async (
    message: string,
    sessionId: string | undefined,
    onDelta: (text: string) => void
  ): Promise<{
    session_id: string;
    reply: string;
    actions?: Array<Record<string, unknown>>;
    tool_name?: string;
    tool_result?: Record<string, unknown>;
  }> => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const t = getToken();
    if (t) headers.Authorization = `Bearer ${t}`;
    const res = await fetch(`${API_BASE}/copilot/chat/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({ message, session_id: sessionId }),
    });
    if (!res.ok) {
      const err = await res.text();
      throw new Error(err || `Copilot stream failed (${res.status})`);
    }
    const reader = res.body?.getReader();
    if (!reader) {
      return request<{
        session_id: string;
        reply: string;
        tool_name?: string;
        tool_result?: Record<string, unknown>;
        actions?: Array<Record<string, unknown>>;
      }>("/copilot/chat", {
        method: "POST",
        body: JSON.stringify({ message, session_id: sessionId }),
      });
    }
    const decoder = new TextDecoder();
    let buffer = "";
    let donePayload: Record<string, unknown> | null = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const data = JSON.parse(line.slice(5).trim()) as Record<string, unknown>;
        if (data.type === "delta" && typeof data.text === "string") onDelta(data.text);
        if (data.type === "done") donePayload = data;
      }
    }
    if (!donePayload) throw new Error("Copilot stream ended without done event");
    return {
      session_id: String(donePayload.session_id || ""),
      reply: String(donePayload.reply || ""),
      actions: (donePayload.actions as Array<Record<string, unknown>>) || [],
      tool_name: donePayload.tool_name as string | undefined,
      tool_result: donePayload.tool_result as Record<string, unknown> | undefined,
    };
  },
  copilotListSessions: () =>
    request<Array<{ id: string; title: string; message_count: number; updated_at: string | null }>>("/copilot/sessions"),
  copilotUsage: () =>
    request<{ is_member: boolean; daily_limit: number | null; daily_used: number; daily_remaining: number | null }>(
      "/copilot/usage"
    ),
  copilotGetSession: (sessionId: string) =>
    request<{
      id: string;
      title: string;
      messages: Array<{
        role: string;
        content: string;
        tool_result?: Record<string, unknown>;
        actions?: Array<Record<string, unknown>>;
      }>;
      context: Record<string, unknown>;
    }>(`/copilot/sessions/${sessionId}`),
  copilotDeleteSession: (sessionId: string) =>
    request<{ deleted: boolean }>(`/copilot/sessions/${sessionId}`, { method: "DELETE" }),
  getCreditPacks: () =>
    request<
      Array<{
        id: string;
        credits: number;
        amount_cents: number;
        amount_fen?: number;
        label: string;
        currency_usd?: string;
        currency_cny?: string;
        price_cny_yuan?: number;
        stripe_enabled?: boolean;
        wechat_enabled?: boolean;
        alipay_enabled?: boolean;
        wechat_vpay_enabled?: boolean;
      }>
    >("/billing/packs"),
  getPaymentMethods: () =>
    request<{ mock_mode: boolean; channels: Array<{ id: string; label: string; enabled: boolean; scenes: Array<{ id: string; label: string; for: string }> }> }>(
      "/billing/methods"
    ),
  getSubscriptionPlans: () =>
    request<
      Array<{
        id: string;
        label: string;
        description?: string;
        monthly_credits: number;
        price_cny_yuan?: number;
        amount_fen?: number;
        wechat_vpay_enabled?: boolean;
      }>
    >("/billing/plans"),
  createPayment: (
    packId: string,
    channel: "wechat" | "alipay" | "stripe",
    scene: string,
    acceptedPaymentTermsVersion?: string,
  ) =>
    request<{
      mode?: string;
      url?: string;
      pay_url?: string;
      code_url?: string;
      out_trade_no?: string;
      credits_granted?: number;
      balance?: number;
      subscription?: { tier: string; status: string; monthly_credits: number; renews_at: string | null };
      payment?: {
        timeStamp: string;
        nonceStr: string;
        package: string;
        signType: string;
        paySign: string;
      };
    }>("/billing/pay", {
      method: "POST",
      body: JSON.stringify({
        pack_id: packId,
        channel,
        scene,
        accepted_payment_terms_version: acceptedPaymentTermsVersion,
      }),
    }),
  createVirtualPayment: (
    packId: string,
    code: string,
    platform: "android" | "windows" | "ios",
    acceptedPaymentTermsVersion?: string,
  ) =>
    request<{
      mode?: string;
      out_trade_no?: string;
      balance?: number;
      env?: number;
      vpay?: {
        mode: string;
        signData: string;
        paySig: string;
        signature: string;
      };
    }>("/billing/vpay/prepare", {
      method: "POST",
      body: JSON.stringify({
        pack_id: packId,
        code,
        platform,
        accepted_payment_terms_version: acceptedPaymentTermsVersion,
      }),
    }),
  listPaymentOrders: (limit = 20) =>
    request<
      Array<{
        out_trade_no: string;
        label: string;
        channel: string;
        amount_yuan: number;
        status: string;
        paid_at?: string | null;
        created_at?: string | null;
      }>
    >(`/billing/orders?limit=${limit}`),
  getPaymentOrderStatus: (outTradeNo: string) =>
    request<{ status: string; balance?: number }>(`/billing/orders/${encodeURIComponent(outTradeNo)}`),
  createCreditCheckout: (packId: string) =>
    request<{ mode: string; url?: string; credits_granted?: number; balance?: number }>("/billing/checkout", {
      method: "POST",
      body: JSON.stringify({ pack_id: packId }),
    }),
  getStructureTemplates: () => request<Array<{ id: string; label: string }>>("/studio/structure-templates"),
  applyStructure: (templateId: string, steps: number) =>
    request<{ waypoints: Array<{ step: number; arousal: number; valence: number; description?: string }> }>(
      "/studio/structure/apply",
      { method: "POST", body: JSON.stringify({ template_id: templateId, steps }) }
    ),
  generateVariations: (
    payload: {
      text_intent?: string;
      seed_work_id?: string;
      title?: string;
      count?: number;
      instrumental?: boolean;
      lyrics?: string;
      style_tags?: string;
      creative_spec?: Record<string, unknown>;
      moods?: string[];
      genres?: string[];
      bpm?: number;
      key?: string;
      reference?: { work_id: string; av_offset?: { arousal?: number; valence?: number } };
      remelt?: boolean;
      mode?: string;
      freedom?: string;
      quality?: string;
      quick?: boolean;
      vocal?: { vocal_gender?: string; vocal_style?: string; language?: string };
      idempotencyKey?: string;
    },
  ) =>
    request<{ id: string; status: string }>("/works/generate/variations", {
      method: "POST",
      idempotencyKey: payload.idempotencyKey,
      body: JSON.stringify(payload),
    }),
  reviseLyrics: (payload: { lyrics: string; instruction: string; line_index?: number; language?: string }) =>
    request<{ lyrics: string }>("/studio/lyrics/revise", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  searchWorks: (q: string) =>
    request<Array<{ id: string; title: string; audio_url: string; moods: string[] }>>(`/works/search?q=${encodeURIComponent(q)}`),
  getCredits: () => request<{ balance: number }>("/users/me/credits"),
  getCreditTransactions: () =>
    request<Array<{ id: string; pack_id: string | null; credits: number; source: string; created_at: string | null }>>(
      "/users/me/credits/transactions"
    ),
  dailyCheckin: () =>
    request<{ credits_granted: number; balance: number; checkin_date: string; streak_days?: number; streak_bonus?: boolean }>(
      "/users/me/checkin",
      { method: "POST" }
    ),
  getProgress: () =>
    request<{
      level: string;
      stats: { published: number; remixes: number; challenge_entries: number };
      checked_in_today: boolean;
      streak_days?: number;
      daily_checkin_credits: number;
      tasks: Array<{ key: string; label: string; credits: number; completed: boolean }>;
    }>("/users/me/progress"),
  getEmotionCalendar: (days = 60) =>
    request<{
      entries: Array<{
        id: string;
        entry_date: string;
        arousal?: number;
        valence?: number;
        work_id?: string;
        mood_tags?: string[];
      }>;
      week_drop?: {
        station?: string;
        station_name?: string;
        station_blurb?: string;
        station_of_day?: string;
        why?: string;
        next_action?: string;
        work?: { work_id: string; title?: string; cover_url?: string } | null;
        radio_trial?: { live?: boolean; status?: string } | null;
      };
    }>(`/users/me/emotion-calendar?days=${days}`),
  getMonthlyEmotionAlbum: (year?: number, month?: number) => {
    const params = new URLSearchParams();
    if (year != null) params.set("year", String(year));
    if (month != null) params.set("month", String(month));
    const q = params.toString();
    return request<{
      year: number;
      month: number;
      title: string;
      track_count: number;
      work_ids: string[];
      tracks: Array<{ work_id: string; title: string; date: string; cover_url?: string }>;
      avg_arousal: number;
      avg_valence: number;
      playlist_id?: string | null;
    }>(`/users/me/emotion-calendar/monthly${q ? `?${q}` : ""}`);
  },
  listPublicPlaylists: (limit = 30) =>
    request<Array<{ id: string; title: string; owner_username?: string; track_count: number; visibility: string }>>(
      `/playlists/discover/public?limit=${limit}`
    ),
  listUserWorkPacks: (username: string) =>
    request<Array<{ id: string; title: string; price_credits: number; work_count: number; owner_username?: string }>>(
      `/ecosystem/users/${encodeURIComponent(username)}/work-packs`
    ),
  getApiUsage: () => request<{ monthly_calls: number; quota: number }>("/users/me/api-usage"),
  getReferral: () =>
    request<{
      referral_code: string;
      invites_count: number;
      credits_earned: number;
      referrer_reward: number;
      invitee_reward: number;
      share_url: string;
    }>("/users/me/referral"),
  estimateCredits: (mode = "single", count = 1, variations?: number) => {
    const params = new URLSearchParams({ mode, count: String(count) });
    if (variations != null) params.set("variations", String(variations));
    return request<{ credits: number; mode: string; breakdown: Array<{ label: string; unit_cost: number; quantity: number; subtotal: number }> }>(
      `/billing/estimate?${params}`
    );
  },
  listDrafts: () =>
    request<Array<{ id: string; title: string; mode: string; payload: Record<string, unknown>; version: number }>>(
      "/studio/drafts",
    ),
  saveDraft: (
    title: string,
    mode: string,
    payload: Record<string, unknown>,
    draftId?: string,
    expectedVersion?: number,
  ) =>
    request<{ id: string; version: number }>("/studio/drafts", {
      method: "POST",
      body: JSON.stringify({
        title,
        mode,
        payload,
        draft_id: draftId,
        expected_version: expectedVersion,
      }),
    }),
  deleteDraft: (draftId: string) =>
    request<{ deleted: boolean }>(`/studio/drafts/${draftId}`, { method: "DELETE" }),
  generateCoverImage: (workId: string, prompt?: string) =>
    request<{ cover_url: string }>("/studio/cover-image", {
      method: "POST",
      body: JSON.stringify({ work_id: workId, prompt: prompt || "" }),
    }),
  updatePlaylist: (id: string, payload: { title?: string; visibility?: string }) =>
    request<{ id: string; title: string; visibility: string }>(`/playlists/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  getTenantMembers: () =>
    request<Array<{ id: string; username: string; email: string; display_name?: string; balance: number }>>(
      "/tenant-admin/members"
    ),
  adminSeed: () => request<{ status: string; presets_seeded?: number }>("/admin/seed", { method: "POST" }),
  adminListPresets: () =>
    request<Array<{ id: string; label: string; category: string; description?: string; enabled: boolean; sort_order: number }>>(
      "/admin/presets"
    ),
  adminDisablePreset: (presetId: string) =>
    request<{ id: string; enabled: boolean }>(`/admin/presets/${encodeURIComponent(presetId)}`, { method: "DELETE" }),
  adminCreatePreset: (payload: {
    id: string;
    label: string;
    category?: string;
    description?: string;
    example_intent?: string;
    moods?: string[];
    genres?: string[];
    bpm_range?: number[];
    key?: string;
    duration_preference?: string;
    default_curve?: string;
    sort_order?: number;
    enabled?: boolean;
  }) =>
    request<{ id: string }>("/admin/presets", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getUserFollowers: (username: string) =>
    request<Array<{ username: string; display_name?: string; avatar_url?: string }>>(
      `/users/${encodeURIComponent(username)}/followers`
    ),
  getUserFollowing: (username: string) =>
    request<Array<{ username: string; display_name?: string; avatar_url?: string }>>(
      `/users/${encodeURIComponent(username)}/following`
    ),
  requestAvatarUpload: (contentType = "image/jpeg") =>
    request<{ storage_key: string; upload_url: string }>("/users/me/avatar/upload-url", {
      method: "POST",
      body: JSON.stringify({ content_type: contentType }),
    }),
  confirmAvatarUpload: (storageKey: string) =>
    request<{ avatar_url: string }>("/users/me/avatar/confirm", {
      method: "POST",
      body: JSON.stringify({ storage_key: storageKey }),
    }),
  listOfficialCatalog: (station?: string) =>
    request<{
      tracks: Array<{
        id: string;
        slug: string;
        title: string;
        caption?: string;
        moods?: string[];
        stations?: string[];
        audio_url: string;
        author?: string;
        official?: boolean;
        discovery_only?: boolean;
      }>;
      discovery_only?: boolean;
    }>(station ? `/catalog/tracks?station=${encodeURIComponent(station)}` : "/catalog/tracks"),
  globalSearch: (q: string) =>
    request<{
      works: Array<{
        id: string;
        title: string;
        audio_url: string;
        hls_url?: string;
        cover_url?: string;
        moods?: string[];
        allow_remix?: boolean;
        license?: string | null;
      }>;
      users: Array<{ username: string; display_name?: string }>;
      posts: Array<{ id: string; caption?: string; work_id: string }>;
    }>(`/search?q=${encodeURIComponent(q)}`),
  getEmbedWork: (workId: string) =>
    request<{ id: string; title: string; audio_url: string; hls_url?: string }>(`/works/embed/${workId}`),
  getEmbedBranding: (workId: string) =>
    request<{ brand: string; logo_url?: string; accent_color?: string; hide_powered_by?: boolean; plan?: string; tenant_id?: string }>(
      `/works/embed/${workId}/branding`
    ),
  getEmbedBrandingByHost: (host: string) =>
    request<{ brand: string; logo_url?: string; accent_color?: string; hide_powered_by?: boolean; tenant_id?: string }>(
      `/config/embed?host=${encodeURIComponent(host)}`
    ),
  batchDeleteWorks: (workIds: string[]) =>
    request<{ deleted: number }>("/works/batch-delete", {
      method: "POST",
      body: JSON.stringify({ work_ids: workIds }),
    }),
  createChallenge: (payload: {
    slug: string;
    title: string;
    description?: string;
    hashtag: string;
    prize_pool_credits?: number;
    prize_winners?: number;
    sponsor_label?: string;
    duration_days?: number;
    ends_at?: string;
  }) => request("/challenges", { method: "POST", body: JSON.stringify(payload) }),
  adminDistributeChallengePrizes: (challengeId: string) =>
    request<{ distributed: number }>(`/ecosystem/challenges/${challengeId}/distribute-prizes`, { method: "POST" }),
  listApiKeys: () =>
    request<Array<{ id: string; name: string; key_prefix: string; scopes?: string[]; created_at: string | null; last_used_at: string | null }>>(
      "/users/me/api-keys"
    ),
  createApiKey: (name: string, scopes?: string[]) =>
    request<{ id: string; name: string; key_prefix: string; scopes?: string[]; api_key: string; created_at: string | null }>(
      "/users/me/api-keys",
      { method: "POST", body: JSON.stringify({ name, scopes: scopes || ["read", "generate"] }) }
    ),
  revokeApiKey: (keyId: string) => request<{ revoked: boolean }>(`/users/me/api-keys/${keyId}`, { method: "DELETE" }),
  listWebhooks: () =>
    request<
      Array<{
        id: string;
        name: string;
        url: string;
        events: string[];
        enabled: boolean;
        created_at: string | null;
        last_delivery_at: string | null;
        last_error: string | null;
      }>
    >("/users/me/webhooks"),
  createWebhook: (name: string, url: string) =>
    request<{ id: string; name: string; url: string; events: string[]; secret: string }>("/users/me/webhooks", {
      method: "POST",
      body: JSON.stringify({ name, url }),
    }),
  deleteWebhook: (id: string) => request<{ deleted: boolean }>(`/users/me/webhooks/${id}`, { method: "DELETE" }),
  adminTenants: () =>
    request<Array<{ tenant_id: string; users: number; works: number; posts: number }>>("/admin/tenants"),
  adminAssignTenant: (userId: string, tenantId: string) =>
    request<{ user_id: string; username: string; tenant_id: string }>(`/admin/users/${userId}/tenant`, {
      method: "PUT",
      body: JSON.stringify({ tenant_id: tenantId }),
    }),
  adminCreateTenant: (payload: {
    tenant_id: string;
    name: string;
    plan?: string;
    invite_code?: string;
    initial_credits?: number;
  }) =>
    request<{ tenant_id: string; name: string; plan: string; credit_pool: number; invite_code?: string }>(
      "/admin/tenants/create",
      { method: "POST", body: JSON.stringify(payload) }
    ),
  adminGrantTenantPool: (tenantId: string, amount: number) =>
    request<{ tenant_id: string; credit_pool: number; granted: number }>(
      `/admin/tenants/${encodeURIComponent(tenantId)}/credits`,
      { method: "POST", body: JSON.stringify({ amount }) }
    ),
  adminSetTenantAdmin: (userId: string, enabled = true) =>
    request<{ user_id: string; username: string; is_tenant_admin: boolean }>(
      `/admin/users/${userId}/tenant-admin?enabled=${enabled ? "true" : "false"}`,
      { method: "PUT" }
    ),
  getTenantAdmin: () =>
    request<{
      tenant_id: string;
      name: string;
      plan: string;
      credit_pool: number;
      member_count: number;
      embed: { brand: string; logo_url?: string; hide_powered_by?: boolean };
    }>("/tenant-admin"),
  updateTenantEmbed: (payload: {
    brand?: string;
    logo_url?: string;
    accent_color?: string;
    hide_powered_by?: boolean;
    custom_domains?: string[];
  }) =>
    request<{ brand: string; logo_url?: string; hide_powered_by?: boolean }>("/tenant-admin/embed", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  allocateTenantCredits: (email: string, amount: number) =>
    request<{ username: string; allocated: number; member_balance: number; pool_remaining: number }>(
      "/tenant-admin/credits/allocate",
      { method: "POST", body: JSON.stringify({ email, amount }) }
    ),
  listReleaseChannels: () =>
    request<{
      channels: Array<{
        code: string;
        name: string;
        region: string;
        distributor_code: string;
        enabled: boolean;
        delivery_mode?: string;
        capability?: "auto" | "wait_connector" | "needs_link";
        auto_default?: boolean;
      }>;
      default_channels?: string[];
      optional_channels?: string[];
      portals?: Array<{ code: string; name: string; region: string; upload_url?: string; sop?: string; clip?: boolean }>;
      aggregators?: Array<{ code: string; name: string; region: string; configured?: boolean }>;
    }>("/releases/channels"),
  listReleases: () => request<{ releases: Array<Record<string, unknown>> }>("/releases"),
  createRelease: (workId: string) =>
    request<Record<string, unknown>>("/releases", { method: "POST", body: JSON.stringify({ work_id: workId }) }),
  quickRelease: (payload: {
    work_id: string;
    consent: boolean;
    mode?: string;
    commission_rate?: number;
    title?: string;
    artist_name?: string;
    selected_channels?: string[];
  }) => request<Record<string, unknown>>("/releases/quick", { method: "POST", body: JSON.stringify(payload) }),
  getReleaseCalendar: () =>
    request<{
      suggestions: Array<{
        work_id: string;
        title?: string;
        cover_url?: string;
        why?: string;
        qc_ready?: boolean;
        channel_suggestion?: { reason?: string; channels?: string[] };
      }>;
      week_drop?: {
        station?: string;
        station_name?: string;
        why?: string;
        next_action?: string;
        work?: { work_id: string; title?: string; cover_url?: string; qc_ready?: boolean } | null;
      };
    }>("/creator/release-calendar"),
  getRelease: (releaseId: string) => request<Record<string, unknown>>(`/releases/${releaseId}`),
  getReleasePassport: (releaseId: string) => request<Record<string, unknown>>(`/releases/${releaseId}/passport`),
  getWorkPassport: (workId: string) => request<Record<string, unknown>>(`/works/${workId}/passport`),
  getWorkSplits: (workId: string) =>
    request<{ shares: Array<{ user_id: string; username?: string; role: string; percent: number }>; max?: number }>(
      `/creator/works/${workId}/splits`,
    ),
  saveWorkSplits: (
    workId: string,
    shares: Array<{ user_id?: string; username?: string; role?: string; percent: number }>,
  ) =>
    request<{ shares: Array<{ user_id: string; username?: string; role: string; percent: number }> }>(
      `/creator/works/${workId}/splits`,
      { method: "PUT", body: JSON.stringify({ shares }) },
    ),
  rematchRoyaltyReports: () => request<{ checked?: number; matched?: number }>("/wallet/reports/rematch", { method: "POST" }),
  listUnattachedSnapshots: () =>
    request<{
      snapshots: Array<{
        id: string;
        channel_code?: string;
        period_key?: string;
        source?: string;
        streams?: number;
        revenue_minor?: number;
        currency?: string;
        usable_for_settlement?: boolean;
        title?: string;
        isrc?: string;
        suggested_work_id?: string;
        suggested_title?: string;
      }>;
    }>("/wallet/unattached"),
  listIsrcBlocked: () =>
    request<{
      snapshots: Array<{
        id: string;
        title?: string;
        isrc?: string;
        channel_code?: string;
        period_key?: string;
        work_id?: string;
        work_title?: string;
        reason?: string;
      }>;
    }>("/wallet/isrc-blocked"),
  attachUnattachedSnapshot: (snapshotId: string, workId: string) =>
    request<{ attached?: boolean; merged?: boolean; snapshot_id?: string; work_id?: string }>(
      `/wallet/unattached/${snapshotId}/attach`,
      { method: "POST", body: JSON.stringify({ work_id: workId }) },
    ),
  getAutoRelease: () => request<{ enabled?: boolean; consented_at?: string | null }>("/creator/auto-release"),
  setAutoRelease: (enabled: boolean) =>
    request<{ enabled?: boolean; consented_at?: string | null }>("/creator/auto-release", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  attachSuggestedSnapshots: () =>
    request<{ attached?: number; checked?: number }>("/wallet/unattached/attach-suggested", { method: "POST" }),
  getProExport: () =>
    request<{ note?: string; rows?: Array<Record<string, unknown>>; csv?: string }>("/creator/pro-export"),
  sharePassportToFeed: (workId: string) =>
    request<{ post_id?: string; caption?: string; created?: boolean; updated?: boolean }>(
      `/creator/works/${workId}/share-passport`,
      { method: "POST" },
    ),
  getCreatorCommune: () => request<Record<string, unknown>>("/creator/commune"),
  createCreatorCommune: (name?: string) =>
    request<Record<string, unknown>>("/creator/commune", { method: "POST", body: JSON.stringify({ name: name || "" }) }),
  inviteCreatorCommune: (payload: { username?: string; invite_code?: string }) =>
    request<Record<string, unknown>>("/creator/commune/invite", { method: "POST", body: JSON.stringify(payload) }),
  leaveCreatorCommune: () => request<Record<string, unknown>>("/creator/commune/leave", { method: "POST" }),
  listSyncTiers: () =>
    request<{ tiers: Array<{ id: string; credits: number; fiat_minor: number; label: string }>; agreement_version?: string }>(
      "/sync/tiers",
    ),
  listSyncCatalog: () =>
    request<{
      listings: Array<{
        work_id: string;
        title?: string;
        cover_url?: string;
        enabled?: boolean;
        commercial?: boolean;
        tiers?: string[];
        tier_cards?: Array<{ id: string; credits: number; fiat_minor: number; label: string }>;
      }>;
    }>("/sync/catalog"),
  getSyncListing: (workId: string) => request<Record<string, unknown>>(`/sync/works/${workId}`),
  saveSyncListing: (workId: string, enabled: boolean, tiers?: string[]) =>
    request<Record<string, unknown>>(`/sync/works/${workId}`, {
      method: "PUT",
      body: JSON.stringify({ enabled, tiers }),
    }),
  placeSyncOrder: (payload: { work_id: string; tier: string; pay_method: string; consent: boolean }) =>
    request<Record<string, unknown>>("/sync/orders", { method: "POST", body: JSON.stringify(payload) }),
  listSyncOrders: (role?: string) =>
    request<{
      orders: Array<{
        id: string;
        work_id?: string;
        tier?: string;
        status?: string;
        seller_minor?: number;
        license_id?: string;
        pay_method?: string;
      }>;
    }>(`/sync/orders${role ? `?role=${encodeURIComponent(role)}` : ""}`),
  listSyncPendingInvoices: () =>
    request<{
      orders: Array<{
        id: string;
        work_id?: string;
        tier?: string;
        status?: string;
        gross_minor?: number;
        seller_minor?: number;
        currency?: string;
        license_id?: string;
      }>;
    }>("/sync/admin/pending"),
  confirmSyncInvoice: (orderId: string) =>
    request<Record<string, unknown>>(`/sync/admin/orders/${orderId}/confirm`, { method: "POST" }),
  reportEmbedComplete: (workId: string, payload: { listen_ratio: number; visitor?: string }) =>
    request<{ duplicate?: boolean; certified?: boolean; usable_for_settlement?: boolean }>(
      `/works/embed/${workId}/complete`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  listRoyaltyReports: () =>
    request<{
      imports: Array<{
        id: string;
        filename?: string;
        source?: string;
        status?: string;
        row_count?: number;
        created_at?: string;
        usable_for_settlement?: boolean;
      }>;
    }>("/wallet/reports"),
  adminRoyaltyReports: () =>
    request<{
      imports: Array<{
        id: string;
        filename?: string;
        source?: string;
        status?: string;
        row_count?: number;
        created_at?: string;
      }>;
    }>("/admin/distribution/reports"),
  adminReleaseWorkbench: (releaseId: string) =>
    request<{
      id?: string;
      workbench?: boolean;
      sla_hours?: number;
      sla_due_at?: string | null;
      sla_overdue?: boolean;
      kit_url?: string;
      has_kit?: boolean;
      cover_url?: string;
      ops_steps?: string[];
      metadata?: Record<string, unknown>;
      deliveries?: Array<Record<string, unknown>>;
      mode?: string;
      status?: string;
    }>(`/admin/distribution/releases/${releaseId}/workbench`),
  releaseKitPath: (releaseId: string) => `/releases/${releaseId}/kit`,
  updateRelease: (releaseId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/releases/${releaseId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  qcRelease: (releaseId: string) =>
    request<Record<string, unknown>>(`/releases/${releaseId}/qc`, { method: "POST" }),
  signReleaseLicense: (releaseId: string, commissionRate = 20, agreementVersion = "2026-08-19") =>
    request<Record<string, unknown>>(`/releases/${releaseId}/license`, {
      method: "POST",
      body: JSON.stringify({ commission_rate: commissionRate, agreement_version: agreementVersion }),
    }),
  submitRelease: (releaseId: string) =>
    request<Record<string, unknown>>(`/releases/${releaseId}/submit`, { method: "POST" }),
  autoSubmitRelease: (
    releaseId: string,
    payload: {
      consent: boolean;
      commission_rate?: number;
      agreement_version?: string;
      mode?: string;
      title?: string;
      artist_name?: string;
      isrc?: string;
      selected_channels?: string[];
    },
  ) =>
    request<Record<string, unknown>>(`/releases/${releaseId}/auto-submit`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  takedownRelease: (releaseId: string) =>
    request<Record<string, unknown>>(`/releases/${releaseId}/takedown`, { method: "POST" }),
  listDeliveries: (workId?: string) =>
    request<{ deliveries: Array<Record<string, unknown>> }>(
      `/distribution/deliveries${workId ? `?work_id=${workId}` : ""}`
    ),
  retryDelivery: (deliveryId: string) =>
    request<Record<string, unknown>>(`/distribution/deliveries/${deliveryId}/retry`, { method: "POST" }),
  setDeliveryStoreUrl: (deliveryId: string, storeUrl: string, externalId?: string) =>
    request<Record<string, unknown>>(`/distribution/deliveries/${deliveryId}/store-url`, {
      method: "POST",
      body: JSON.stringify({ store_url: storeUrl, external_id: externalId }),
    }),
  listDistributorBindings: () => request<{ bindings: Array<Record<string, unknown>> }>("/distribution/bindings"),
  bindDistributor: (provider: string, officialToken?: string, externalReleaseId?: string) =>
    request<Record<string, unknown>>("/distribution/bindings", {
      method: "POST",
      body: JSON.stringify({ provider, official_token: officialToken, external_release_id: externalReleaseId }),
    }),
  unbindDistributor: (provider: string) =>
    request<Record<string, unknown>>(`/distribution/bindings/${encodeURIComponent(provider)}`, { method: "DELETE" }),
  listAnalyticsSources: () => request<Record<string, unknown>>("/distribution/analytics/sources"),
  syncCreatorAnalytics: () =>
    request<Record<string, unknown>>("/distribution/analytics/sync", { method: "POST" }),
  youtubeOauthUrl: () => request<{ configured: boolean; url?: string | null }>("/distribution/youtube/oauth-url"),
  getCreatorHub: () => request<Record<string, unknown>>("/creator/hub"),
  getCreatorWork: (workId: string) => request<Record<string, unknown>>(`/creator/works/${workId}`),
  getCreatorSettlements: (periodKey?: string) =>
    request<{ settlements: Array<Record<string, unknown>> }>(
      periodKey ? `/creator/settlements?period_key=${encodeURIComponent(periodKey)}` : "/creator/settlements",
    ),
  getCreatorSettlement: (batchId: string) => request<Record<string, unknown>>(`/creator/settlements/${batchId}`),
  getCreatorStatement: (periodKey?: string) =>
    request<{
      filename?: string;
      csv?: string;
      receipt_text?: string;
      receipt_no?: string;
      batches?: number;
      by_currency?: Array<Record<string, unknown>>;
      note?: string;
      next_payout_date?: string;
      days_until_payout?: number;
      credits_excluded?: boolean;
    }>(
      periodKey ? `/creator/statement?period_key=${encodeURIComponent(periodKey)}` : "/creator/statement",
    ),
  getRoyaltyWallet: () => request<Record<string, unknown>>("/wallet"),
  listPayoutAccounts: () => request<{ accounts: Array<Record<string, unknown>> }>("/wallet/payout-accounts"),
  addPayoutAccount: (payload: { channel: string; account_name?: string; account_no: string; is_default?: boolean }) =>
    request<Record<string, unknown>>("/wallet/payout-accounts", { method: "POST", body: JSON.stringify(payload) }),
  deletePayoutAccount: (accountId: string) =>
    request<Record<string, unknown>>(`/wallet/payout-accounts/${accountId}`, { method: "DELETE" }),
  requestRoyaltyWithdraw: (payload: { amount_minor: number; currency?: string; channel?: string; payout_account_id?: string }) =>
    request<Record<string, unknown>>("/wallet/withdraw", { method: "POST", body: JSON.stringify(payload) }),
  requestKycReview: () =>
    request<{ kyc_status?: string; provider_configured?: boolean; verified?: boolean; note?: string }>(
      "/wallet/kyc-request",
      { method: "POST" },
    ),
  adminKycQueue: (status: "none" | "pending" | "verified" | "rejected" = "pending") =>
    request<{ status?: string; users?: Array<{ id?: string; email?: string; username?: string; kyc_status?: string }> }>(
      `/admin/kyc?status=${encodeURIComponent(status)}`,
    ),
  uploadRoyaltyReport: (file: File, source = "user_export", distributorCode?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("source", source);
    if (distributorCode) form.append("distributor_code", distributorCode);
    return uploadRequest<Record<string, unknown>>("/wallet/reports", form);
  },
  adminSyncAnalytics: () =>
    request<Record<string, unknown>>("/admin/distribution/analytics/sync", { method: "POST" }),
  adminDistributionDeliveries: () => request<{ deliveries: Array<Record<string, unknown>> }>("/admin/distribution/deliveries"),
  adminSetDeliveryStatus: (
    deliveryId: string,
    status: string,
    reason?: string,
    extra?: { store_url?: string; external_id?: string },
  ) =>
    request<Record<string, unknown>>(`/admin/distribution/deliveries/${deliveryId}/status`, {
      method: "POST",
      body: JSON.stringify({ status, reason, store_url: extra?.store_url, external_id: extra?.external_id }),
    }),
  adminMarkReleaseLive: (releaseId: string, storeUrl?: string) =>
    request<Record<string, unknown>>(`/admin/distribution/releases/${releaseId}/mark-live`, {
      method: "POST",
      body: JSON.stringify({ store_url: storeUrl }),
    }),
  adminSettlementBatches: () => request<{ batches: Array<Record<string, unknown>> }>("/admin/settlement/batches"),
  adminSettlementBatch: (batchId: string) => request<Record<string, unknown>>(`/admin/settlement/batches/${batchId}`),
  adminSettlementPreview: () =>
    request<{
      period_key?: string;
      unsettled_for_period?: number;
      revenue_minor_for_period?: number;
      unsettled_other_periods?: Array<{ period_key?: string; count?: number; revenue_minor?: number }>;
      needs_confirm?: boolean;
      draft_batch_id?: string | null;
      pending_ops_connector_batches?: number;
      pending_user_connector_batches?: number;
      gross_minor_for_period?: number;
      commission_minor_for_period?: number;
      net_minor_for_period?: number;
      by_currency?: Array<{ currency?: string; gross_minor?: number; commission_minor?: number; net_minor?: number }>;
      by_rate?: Array<{ rate?: number; count?: number; net_minor?: number }>;
      skipped?: { self_release?: number; no_user?: number; below_minimum?: number; already_in_batch?: number; non_positive?: number };
      supplemental?: boolean;
      has_confirmed_batch?: boolean;
    }>("/admin/settlement/preview"),
  adminRunSettlement: (periodKey?: string) =>
    request<Record<string, unknown>>("/admin/settlement/run", {
      method: "POST",
      body: JSON.stringify({ period_key: periodKey }),
    }),
  adminConfirmSettlement: (batchId: string) =>
    request<Record<string, unknown>>(`/admin/settlement/${batchId}/confirm`, { method: "POST" }),
  adminVoidSettlement: (batchId: string) =>
    request<Record<string, unknown>>(`/admin/settlement/${batchId}/void`, { method: "POST" }),
  adminWithdrawals: () => request<{ withdrawals: Array<Record<string, unknown>> }>("/admin/settlement/withdrawals"),
  adminReviewWithdrawal: (id: string, approve: boolean, note?: string) =>
    request<Record<string, unknown>>(`/admin/settlement/withdrawals/${id}/review`, {
      method: "POST",
      body: JSON.stringify({ approve, admin_note: note }),
    }),
  adminSetKyc: (userId: string, status: "none" | "pending" | "verified" | "rejected") =>
    request<{ user_id?: string; kyc_status?: string }>(`/admin/users/${userId}/kyc`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  adminListUsers: (q?: string, banned?: boolean) =>
    request<{ users: Array<{ id: string; email?: string; username?: string; is_active?: boolean; kyc_status?: string }> }>(
      `/admin/users?${new URLSearchParams({
        ...(q ? { q } : {}),
        ...(banned === undefined ? {} : { banned: String(banned) }),
      }).toString()}`
    ),
  adminBanUser: (userId: string) =>
    request<{ user_id: string; banned: boolean }>(`/admin/users/${userId}/ban`, { method: "POST" }),
  adminUnbanUser: (userId: string) =>
    request<{ user_id: string; banned: boolean }>(`/admin/users/${userId}/ban`, { method: "DELETE" }),
  mintConnectorToken: () =>
    request<{
      token: string;
      role: string;
      expires_at?: string | null;
      pair_text?: string;
      api_base?: string;
      pair?: { vibePair?: number; apiBase: string; token: string; role?: string };
    }>(
      "/distribution/connector/token",
      { method: "POST" },
    ),
  revokeConnectorToken: () =>
    request<{ ok?: boolean; revoked?: number }>("/distribution/connector/token", { method: "DELETE" }),
  listSeats: () =>
    request<{
      seats: Array<{
        id: string;
        ownership: string;
        channel_code: string;
        status: string;
        last_harvest_at?: string | null;
        last_upload_at?: string | null;
        has_session?: boolean;
        needs_challenge?: boolean;
        playbook?: { name?: string };
      }>;
      playbooks: Array<{ code: string; name?: string; region?: string }>;
    }>("/seats"),
  connectSeat: (channelCode: string) =>
    request<Record<string, unknown>>("/seats/connect", {
      method: "POST",
      body: JSON.stringify({ channel_code: channelCode }),
    }),
  disconnectSeat: (seatId: string) =>
    request<Record<string, unknown>>(`/seats/${seatId}/disconnect`, { method: "POST" }),
  bindSeatSession: (seatId: string, payload: { cookies?: unknown; storage_state?: Record<string, unknown>; credentials?: Record<string, unknown> }) =>
    request<Record<string, unknown>>(`/seats/${seatId}/session`, { method: "POST", body: JSON.stringify(payload) }),
  harvestSeat: (seatId: string) => request<Record<string, unknown>>(`/seats/${seatId}/harvest`, { method: "POST" }),
  ingestHarvestRows: (payload: { seat_id?: string; channel_code?: string; period_key?: string; rows: Array<Record<string, unknown>> }) =>
    request<Record<string, unknown>>("/seats/harvest", { method: "POST", body: JSON.stringify(payload) }),
  ingestSeatSync: (payload: { seat_id?: string; channel_code?: string; period_key?: string; rows: Array<Record<string, unknown>> }) =>
    request<Record<string, unknown>>("/seats/sync", { method: "POST", body: JSON.stringify(payload) }),
  updateSeatScopes: (seatId: string, scopes: Record<string, boolean>) =>
    request<Record<string, unknown>>(`/seats/${seatId}/scopes`, { method: "PATCH", body: JSON.stringify(scopes) }),
  revokeSeatScopes: (seatId: string) =>
    request<Record<string, unknown>>(`/seats/${seatId}/scopes/revoke`, { method: "POST" }),
  commandSeat: (seatId: string, kind: string, payload?: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/seats/${seatId}/command`, { method: "POST", body: JSON.stringify({ kind, payload }) }),
  listSeatConnections: () =>
    request<{
      connections: Array<{
        channel_code: string;
        name?: string;
        status?: string;
        suggest_connector?: boolean;
        seat_id?: string;
        scopes?: Record<string, boolean> | null;
        portal?: string;
        delivery_mode?: string;
      }>;
    }>("/seats/connections"),
  listSeatJobs: (channelCode?: string) =>
    request<{ jobs: Array<Record<string, unknown>> }>(
      channelCode ? `/seats/jobs?channel_code=${encodeURIComponent(channelCode)}` : "/seats/jobs",
    ),
  completeSeatJob: (jobId: string, ok = true, result?: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/seats/jobs/${jobId}/complete`, {
      method: "POST",
      body: JSON.stringify({ ok, result }),
    }),
  startSeatRemoteLogin: (seatId: string) =>
    request<Record<string, unknown>>(`/seats/${seatId}/remote-login`, { method: "POST" }),
  seatRemoteStatus: (seatId: string) => request<Record<string, unknown>>(`/seats/${seatId}/remote`),
  ackSeatRemoteLogin: (seatId: string) =>
    request<Record<string, unknown>>(`/seats/${seatId}/remote/ack`, { method: "POST" }),
  kickSeatRuntime: (seatId: string) =>
    request<{ ok: boolean; kicked?: boolean }>(`/seats/${seatId}/runtime-kick`, { method: "POST" }),
  listHarvestUnmatched: () => request<{ rows: Array<Record<string, unknown>> }>("/seats/unmatched"),
  attachHarvestUnmatched: (unmatchedId: string, workId: string) =>
    request<Record<string, unknown>>(`/seats/unmatched/${unmatchedId}/attach`, {
      method: "POST",
      body: JSON.stringify({ work_id: workId }),
    }),
  adminHarvestUnmatched: () => request<{ rows: Array<Record<string, unknown>> }>("/admin/harvest/unmatched"),
  adminSeatsHealth: () =>
    request<{
      queued?: number;
      failed?: number;
      selector_broke?: number;
      login_wall?: number;
      seats?: Array<{ channel_code?: string; ownership?: string; status?: string; farm_health?: Record<string, unknown> }>;
    }>("/admin/seats/health"),
  adminAttachHarvestUnmatched: (unmatchedId: string, workId: string) =>
    request<Record<string, unknown>>(
      `/admin/harvest/unmatched/${unmatchedId}/attach?work_id=${encodeURIComponent(workId)}`,
      { method: "POST" },
    ),
  ingestConnectorRows: (payload: { channel_code?: string; period_key?: string; rows: Array<Record<string, unknown>> }) =>
    request<Record<string, unknown>>("/distribution/connector/ingest", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listConnectorClaims: () => request<{ claims: Array<Record<string, unknown>> }>("/distribution/connector/claims"),
  matchConnectorClaim: (claimId: string, workId: string) =>
    request<Record<string, unknown>>(`/distribution/connector/claims/${claimId}/match`, {
      method: "POST",
      body: JSON.stringify({ work_id: workId }),
    }),
  adminDistributionHealth: () =>
    request<{
      submitting?: number;
      ops_queue?: number;
      stale_submitting?: number;
      queued_without_deliveries?: number;
      healthy?: boolean;
    }>("/admin/distribution/health"),
  adminDistributionPartners: () =>
    request<{
      partners?: Array<{
        code?: string;
        name?: string;
        region?: string;
        configured?: boolean;
        has_key?: boolean;
        has_base?: boolean;
        settlement_path?: string;
      }>;
      global_ready?: boolean;
      cn_ready?: boolean;
      stub_enabled?: boolean;
      note?: string;
    }>("/admin/distribution/partners"),
  adminUnmatchedOfficial: () =>
    request<{
      snapshots?: Array<{
        id: string;
        title?: string;
        isrc?: string;
        channel_code?: string;
        period_key?: string;
        work_id?: string;
        work_title?: string;
        suggested_work_id?: string;
        reason?: string;
      }>;
    }>("/admin/distribution/reports/unmatched"),
  adminAttachOfficialSnapshot: (snapshotId: string, workId: string) =>
    request<Record<string, unknown>>(`/admin/distribution/reports/snapshots/${snapshotId}/attach?work_id=${encodeURIComponent(workId)}`, {
      method: "POST",
    }),
  adminReconcileDistribution: () =>
    request<Record<string, unknown>>("/admin/distribution/reconcile", { method: "POST" }),
  adminDistributionQueue: () =>
    request<{ deliveries: Array<Record<string, unknown>> }>("/admin/distribution/deliveries?queue_only=true"),
  adminRetryDelivery: (deliveryId: string) =>
    request<Record<string, unknown>>(`/admin/distribution/deliveries/${deliveryId}/retry`, { method: "POST" }),
  adminClaimDelivery: (deliveryId: string) =>
    request<Record<string, unknown>>(`/admin/distribution/deliveries/${deliveryId}/claim`, { method: "POST" }),
  adminUnclaimDelivery: (deliveryId: string) =>
    request<Record<string, unknown>>(`/admin/distribution/deliveries/${deliveryId}/unclaim`, { method: "POST" }),
  adminDeliveryPack: (deliveryId: string) =>
    request<{
      kit_url?: string;
      has_kit?: boolean;
      title?: string;
      artist_name?: string;
      isrc?: string;
      ops_steps?: string[];
      selected_channels?: string[];
      clip_pack_url?: string;
      originality_zip_url?: string;
      listing_asset?: string;
      asset_status?: {
        listing?: { label?: string; ready?: boolean };
        evidence?: { label?: string; needed?: boolean; ready?: boolean };
      };
      clip_windows?: Array<{ length?: number; start?: number; end?: number }>;
    }>(`/admin/distribution/deliveries/${deliveryId}/pack`),
  adminConnectorBatches: () =>
    request<{ batches: Array<Record<string, unknown>> }>("/admin/distribution/connector/batches"),
  adminConnectorClaims: (status = "unclaimed") =>
    request<{ claims: Array<Record<string, unknown>> }>(`/admin/distribution/connector/claims?status=${status}`),
  adminConfirmConnectorBatch: (batchId: string) =>
    request<Record<string, unknown>>(`/admin/distribution/connector/batches/${batchId}/confirm`, { method: "POST" }),
  adminMatchConnectorClaim: (claimId: string, workId: string) =>
    request<Record<string, unknown>>(`/admin/distribution/connector/claims/${claimId}/match`, {
      method: "POST",
      body: JSON.stringify({ work_id: workId }),
    }),
  adminImportReport: (file: File, source = "distributor_export", distributorCode?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("source", source);
    if (distributorCode) form.append("distributor_code", distributorCode);
    return uploadRequest<Record<string, unknown>>("/admin/distribution/reports", form);
  },
};

const apiExtras = {
  getLegalMeta: () =>
    request<{
      company_name?: string;
      contact_email?: string;
      contact_phone?: string;
      icp_number?: string;
      effective_date?: string;
      required_versions?: Record<string, string>;
    }>("/legal/meta"),
  getLegalDocuments: (locale?: string) =>
    request<{
      documents: Array<{ slug: string; title: string; version: string; required_for: string[] }>;
      required_versions: Record<string, string>;
    }>(locale ? `/legal/documents?locale=${encodeURIComponent(locale)}` : "/legal/documents"),
  getLegalDocument: (slug: string, locale?: string) =>
    request<{ slug: string; title: string; version: string; content: string; effective_date?: string; locale?: string }>(
      locale ? `/legal/documents/${slug}?locale=${encodeURIComponent(locale)}` : `/legal/documents/${slug}`,
    ),
  getConsentStatus: () =>
    request<{
      missing: string[];
      required_versions: Record<string, string>;
      analytics_consent?: boolean;
      ai_notice_accepted?: boolean;
      deletion_scheduled_at?: string | null;
    }>("/legal/consents/status"),
  recordConsents: (consents: Array<{ consent_type: string; version?: string }>, analyticsConsent?: boolean) =>
    request("/legal/consents", {
      method: "POST",
      body: JSON.stringify({ consents, analytics_consent: analyticsConsent }),
    }),
  exportMyData: () => request<Record<string, unknown>>("/users/me/export"),
  deleteAccount: (password?: string) =>
    request<{ scheduled: boolean; deletion_at: string; grace_days: number }>("/users/me/delete-account", {
      method: "POST",
      body: JSON.stringify({ confirm: true, password }),
    }),
  cancelAccountDeletion: () =>
    request<{ cancelled: boolean }>("/users/me/cancel-deletion", { method: "POST" }),
  updateConsents: (analyticsConsent: boolean) =>
    request("/users/me/consents", {
      method: "PUT",
      body: JSON.stringify({ analytics_consent: analyticsConsent }),
    }),
  tipWork: (workId: string, credits: number, publicMessage?: string) =>
    request<{ tipped: number; public?: boolean }>(`/ecosystem/works/${workId}/tip`, {
      method: "POST",
      body: JSON.stringify({ credits, public_message: publicMessage }),
    }),
  getPublicTips: (workId: string) =>
    request<{ tips: Array<{ username: string; credits: number; message?: string; created_at?: string }> }>(
      `/ecosystem/works/${workId}/public-tips`
    ),
  exportWork: (workId: string, exportType: "hq_mp3" | "hq_wav" | "stems" | "commercial_license") =>
    request<{ download_url: string; license_id?: string; meta: Record<string, unknown> }>(
      `/ecosystem/works/${workId}/export`,
      { method: "POST", body: JSON.stringify({ export_type: exportType }) }
    ),
  listRecipeTemplates: () =>
    request<Array<{ id: string; title: string; description?: string; price_credits: number; purchase_count?: number }>>(
      "/ecosystem/templates"
    ),
  listWorkPacks: () =>
    request<Array<{ id: string; title: string; price_credits: number; work_count: number; owner_username?: string }>>(
      "/ecosystem/work-packs"
    ),
  purchaseWorkPack: (packId: string) =>
    request<{ work_ids: string[]; title?: string }>(`/ecosystem/work-packs/${packId}/purchase`, { method: "POST" }),
  purchaseRecipeTemplate: (templateId: string) =>
    request<{ spec: Record<string, unknown>; reference_work_id?: string }>(`/ecosystem/templates/${templateId}/purchase`, {
      method: "POST",
    }),
  getCreatorWallet: () =>
    request<{
      balance_credits: number;
      lifetime_earned: number;
      estimated_weekly_royalty?: number;
      remix_credits_7d?: number;
      ledger?: string;
      recent_tips?: Array<{ amount: number; from_user_id?: string; created_at?: string | null }>;
      recent_royalties?: Array<{ credits: number; created_at?: string | null }>;
      recent_remix_credits?: Array<{ credits: number; created_at?: string | null }>;
    }>("/ecosystem/wallet"),
  getMemberExportQuotas: () =>
    request<{
      is_member: boolean;
      capabilities?: { stems?: boolean; hq_wav?: boolean; ai_cover?: boolean; mv_video?: boolean };
      stems: { used: number; limit: number; remaining: number; available?: boolean };
      hq_wav: { used: number; limit: number; remaining: number; available?: boolean };
      ai_cover: { used: number; limit: number; remaining: number; available?: boolean };
      mv_video: { used: number; limit: number; remaining: number; available?: boolean };
    }>("/ecosystem/member-quotas"),
  listMyExports: () =>
    request<{
      exports: Array<{
        id: string;
        work_id: string;
        export_type: string;
        status: string;
        download_url?: string;
        title?: string;
        license_id?: string;
        created_at?: string;
      }>;
    }>("/ecosystem/exports"),
  requestInvoice: (payload: { order_id: string; title: string; email: string; tax_id?: string }) =>
    request<{ id: string; status: string; message: string }>("/ecosystem/invoices", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listMyInvoices: () =>
    request<{
      invoices: Array<{
        id: string;
        order_id: string;
        title: string;
        email: string;
        status: string;
        created_at?: string;
      }>;
    }>("/ecosystem/invoices"),
  getCnRecurringStatus: () =>
    request<{ available: boolean; message: string; on_waitlist?: boolean; manual_renewal?: boolean }>(
      "/billing/cn-recurring/status"
    ),
  joinCnRecurringWaitlist: (channel: "wechat" | "alipay" = "wechat") =>
    request<{ joined: boolean; channel: string; duplicate?: boolean }>("/billing/cn-recurring/waitlist", {
      method: "POST",
      body: JSON.stringify({ channel }),
    }),
  createSupportTicket: (payload: {
    category: "refund" | "billing" | "technical";
    subject: string;
    body: string;
    order_id?: string;
  }) =>
    request<{ id: string; status: string }>("/ecosystem/support-tickets", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listSupportTickets: () =>
    request<{
      tickets: Array<{
        id: string;
        category: string;
        subject: string;
        status: string;
        resolution?: string;
        admin_note?: string;
        credits_granted?: number;
        created_at?: string;
        resolved_at?: string;
      }>;
    }>("/ecosystem/support-tickets"),
  adminListSupportTickets: () =>
    request<{
      tickets: Array<{
        id: string;
        category: string;
        subject: string;
        body: string;
        status: string;
        order_id?: string;
        user_email?: string;
        created_at?: string;
      }>;
    }>("/ecosystem/admin/support-tickets"),
  adminResolveSupportTicket: (
    ticketId: string,
    payload: {
      resolution: "approved" | "rejected" | "credits_granted" | "stripe_refunded";
      admin_note?: string;
      credits_compensation?: number;
      attempt_stripe_refund?: boolean;
    }
  ) =>
    request<{ id: string; status: string; resolution?: string }>(`/ecosystem/admin/support-tickets/${ticketId}/resolve`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  adminCnRecurringWaitlist: () =>
    request<{
      entries: Array<{ user_id: string; email?: string; channel: string; created_at?: string }>;
    }>("/ecosystem/admin/cn-recurring-waitlist"),
  adminListModerationWords: () =>
    request<Array<{ id: string; pattern: string; category: string; level: string; enabled: boolean }>>(
      "/admin/moderation-words"
    ),
  adminCreateModerationWord: (payload: { pattern: string; category?: string; level?: string }) =>
    request<{ id: string }>("/admin/moderation-words", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  adminDeleteModerationWord: (wordId: string) =>
    request<{ disabled: boolean }>(`/admin/moderation-words/${wordId}`, { method: "DELETE" }),
  listenCheckin: (payload: {
    work_id: string;
    listen_ratio: number;
    arousal?: number;
    valence?: number;
    mood_tags?: string[];
    station?: string;
  }) =>
    request<{
      duplicate?: boolean;
      resonance_score?: number;
      credits_granted?: number;
      self_listen?: boolean;
      settled?: boolean;
      payout_minor?: number;
    }>("/engagement/listen-checkin", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getMoodRadio: (limit = 3, station?: string) =>
    request<{
      tracks: Array<{
        work_id: string;
        post_id?: string;
        title: string;
        author: string;
        cover_url?: string;
        audio_url?: string;
        moods?: string[];
        featured?: boolean;
        trial?: boolean;
        station?: string;
      }>;
      stations?: Array<{ code: string; name?: string; blurb?: string; of_the_day?: boolean }>;
      station_of_day?: string;
      chart?: Array<{ rank: number; work_id: string; title?: string; completes?: number }>;
      usable_for_settlement?: boolean;
      rules?: {
        channel_code?: string;
        min_listen_ratio?: number;
        usable_for_settlement?: boolean;
        note?: string;
        member_revenue_minor_per_complete?: number;
      };
    }>(`/engagement/mood-radio?limit=${limit}${station ? `&station=${encodeURIComponent(station)}` : ""}`),
  getRadioStation: (station?: string, limit = 8) =>
    request<Record<string, unknown>>(
      station
        ? `/engagement/radio/stations/${encodeURIComponent(station)}?limit=${limit}`
        : `/engagement/radio/stations?limit=${limit}`,
    ),
  startRadioTrial: (workId: string, station?: string) =>
    request<Record<string, unknown>>(`/creator/works/${workId}/radio-trial`, {
      method: "POST",
      body: JSON.stringify({ station: station || null }),
    }),
  getRadioTrial: (workId: string) => request<Record<string, unknown>>(`/creator/works/${workId}/radio-trial`),
  addClipDrop: (workId: string, url: string, clipLength = 15) =>
    request<Record<string, unknown>>(`/creator/works/${workId}/clip-drops`, {
      method: "POST",
      body: JSON.stringify({ url, clip_length: clipLength }),
    }),
  listClipDrops: (workId: string) =>
    request<{ drops: Array<{ id: string; portal_code?: string; portal_name?: string; url?: string; clip_length?: number; display_only?: boolean }> }>(
      `/creator/works/${workId}/clip-drops`,
    ),
  listWorkClips: (workId: string) =>
    request<{
      work_id?: string;
      clip_windows?: Array<{ length?: number; start?: number; end?: number; use?: string }>;
      clip_drops?: Array<{ id: string; portal_code?: string; portal_name?: string; url?: string; clip_length?: number; display_only?: boolean }>;
      display_only?: boolean;
      note?: string;
    }>(`/creator/works/${workId}/clips`),
  getRemixChain: (workId: string) =>
    request<{ work_id: string; generation_depth: number; direct_remixes: number; chain_label: string }>(
      `/engagement/remix-chain/${workId}`
    ),
  getDuelQuota: () =>
    request<{
      member_free_remaining: number;
      pass_starts_remaining: number;
      start_cost: number;
      is_member: boolean;
    }>("/engagement/duel-quota"),
  getWorkEngagementStats: (workId: string) =>
    request<{
      work_id: string;
      listen_completes: number;
      resonance_avg: number;
      resonance_count: number;
    }>(`/engagement/work-stats/${workId}`),
  getCreatorWeeklySummary: () =>
    request<{
      listens: number;
      tips: number;
      published: number;
      remixes: number;
      duel_mentions?: number;
      radio_completes?: number;
      radio_self_completes?: number;
      wallet_split?: {
        credits_tips?: number;
        radio_minor?: number;
        sync_minor?: number;
        embed_minor?: number;
        dsp_minor?: number;
      };
      payout_calendar?: {
        next_payout_date?: string;
        weekday_label?: string;
        days_until_payout?: number;
        is_payout_day?: boolean;
      };
    }>("/engagement/creator-weekly-summary"),
  getChart: (chartType: string, period = "week") =>
    request<{
      chart_type: string;
      period: string;
      entries: Array<Record<string, unknown>>;
    }>(`/community/charts/${chartType}?period=${period}`),
  getChartHistory: (chartType: string, periodKey?: string) =>
    request<{
      chart_type: string;
      period_key?: string | null;
      snapshot_at?: string | null;
      entries: Array<Record<string, unknown>>;
    }>(`/community/charts/${chartType}/history${periodKey ? `?period_key=${periodKey}` : ""}`),
  getActivityStream: (scope: "global" | "following" = "global", limit = 30) =>
    request<{ events: Array<Record<string, unknown>> }>(`/community/activity-stream?scope=${scope}&limit=${limit}`),
  listDuels: (status?: string) =>
    request<{ duels: Array<Record<string, unknown>> }>(`/community/duels${status ? `?status=${status}` : ""}`),
  getDuel: (duelId: string) => request<Record<string, unknown>>(`/community/duels/${duelId}`),
  createDuel: (workId: string, opponentUsername?: string) =>
    request<{ duel_id: string; status: string }>("/community/duels", {
      method: "POST",
      body: JSON.stringify({ work_id: workId, opponent_username: opponentUsername }),
    }),
  acceptDuel: (duelId: string, workId: string) =>
    request<{ duel_id: string; status: string }>(`/community/duels/${duelId}/accept`, {
      method: "POST",
      body: JSON.stringify({ work_id: workId }),
    }),
  voteDuel: (duelId: string, side: "a" | "b", listenRatio: number, emotionTag?: string) =>
    request<{ voted: boolean }>(`/community/duels/${duelId}/vote`, {
      method: "POST",
      body: JSON.stringify({ side, listen_ratio: listenRatio, emotion_tag: emotionTag }),
    }),
};
Object.assign(api, apiExtras);
export type VibeApi = typeof api & typeof apiExtras;
export const vibeApi: VibeApi = api as VibeApi;
