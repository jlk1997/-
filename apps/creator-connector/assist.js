(() => {
  const api = window.__vibePlaybooks;
  const job = window.__vibeAssistJob;
  if (!api || !job) return { ok: false, reason: "no_job" };
  api.banner(job);
  const filled = api.fillJob(job);
  const live = api.looksLive(location.href, job.channel_code);
  return { ok: true, filled: filled.filled, live, url: location.href, delivery_id: job.delivery_id };
})();
