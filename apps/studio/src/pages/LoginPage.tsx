import { ApiError, setToken, vibeApi } from "@vibe-sorcery/api-client";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { deskCopy } from "../copy";

export function LoginPage() {
  const copy = deskCopy();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await vibeApi.login(email.trim(), password);
      localStorage.setItem("token", res.access_token);
      setToken(res.access_token);
      await client.invalidateQueries({ queryKey: ["me"] });
      navigate("/create");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="login" onSubmit={submit}>
      <h1>{copy.brand}</h1>
      <p>{copy.studioLead}</p>
      <label>{copy.email}<input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" /></label>
      <label>{copy.password}<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
      {error ? <p className="error">{error}</p> : null}
      <button type="submit" disabled={busy}>{copy.login}</button>
    </form>
  );
}
