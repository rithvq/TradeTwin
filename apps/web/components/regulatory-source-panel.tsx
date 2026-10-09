"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, RefreshCw, Sparkles, Save, Check, Upload } from "lucide-react";
import { complianceApiBaseUrl } from "@/lib/compliance";

type Snapshot = { id: string; url: string; fetched_at: string; content_hash: string; text: string; changed: boolean };
type Review = { id: string; regulation_id: string; status: string; quote: string; rule: unknown };
type Catalog = { mode: string; llm_configured: boolean; sources: {title: string; url: string}[]; snapshots: Snapshot[]; reviews: Review[] };

export function RegulatorySourcePanel() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [url, setUrl] = useState("https://gstcouncil.gov.in/cgst-tax-notification");
  const [selected, setSelected] = useState("");
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const request = useCallback(async (path: string, body?: unknown) => {
    const response = await fetch(`${complianceApiBaseUrl}${path}`, body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed. Check rule fields and your administrator role.");
    return data;
  }, []);
  const reload = useCallback(async () => setCatalog(await request("/regulatory-sources")), [request]);
  useEffect(() => { void reload().catch(error => setMessage(String(error))); }, [reload]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setMessage("");
    try { await action(); await reload(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Request failed"); }
    finally { setBusy(false); }
  }
  const snapshot = catalog?.snapshots.find(item => item.id === selected);
  const button = "inline-flex items-center gap-2 rounded border px-3 py-2 text-sm disabled:opacity-50";
  return <section className="space-y-4 border-b p-6" aria-labelledby="source-heading">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h1 id="source-heading" className="text-xl font-semibold">Regulatory source review</h1>
      <button className={button} disabled={busy} onClick={() => void run(reload)}><RefreshCw size={16}/>Refresh</button>
    </div>
    <p role="status">{catalog?.mode === "demo" ? "Demo catalog active. Bundled rules are included in assessments." : "Database catalog active. Only published versions are evaluated."}</p>
    <p className="text-sm">Source retrieval does not establish complete legal coverage. AI drafts require human review of effective dates, scope and exceptions.</p>
    <label className="block text-sm font-medium">Official source URL
      <input className="mt-1 w-full rounded border p-2" value={url} onChange={e => setUrl(e.target.value)} list="official-sources"/>
    </label>
    <datalist id="official-sources">{catalog?.sources.map(source => <option key={source.url} value={source.url}>{source.title}</option>)}</datalist>
    <button className={button} disabled={busy} onClick={() => void run(async () => {
      const result = await request("/regulatory-sources/fetch", {url}); setSelected(result.id); setDraft(""); setMessage("Source retrieved. No rules changed.");
    })}><Download size={16}/>Fetch source</button>
    <label className="block text-sm font-medium">Source snapshot
      <select className="mt-1 w-full rounded border p-2" value={selected} onChange={e => {setSelected(e.target.value); setDraft("");}}>
        <option value="">Select a snapshot</option>
        {catalog?.snapshots.map(item => <option key={item.id} value={item.id}>{new Date(item.fetched_at).toLocaleString()} | {item.url}{item.changed ? " | Changed" : ""}</option>)}
      </select>
    </label>
    {snapshot && <>
      <details><summary className="cursor-pointer">Retrieved source text</summary><p className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-sm">{snapshot.text}</p><p className="break-all text-xs">SHA-256: {snapshot.content_hash}</p></details>
      <button className={button} disabled={busy || !catalog?.llm_configured} onClick={() => void run(async () => {
        setDraft(JSON.stringify(await request(`/regulatory-sources/${selected}/suggest`, {}), null, 2));
      })}><Sparkles size={16}/>Suggest draft</button>
      {!catalog?.llm_configured && <p className="text-sm">AI drafting is not configured. Manual reviewed drafts remain available.</p>}
      <label className="block text-sm font-medium">Draft JSON (rule and supporting quote)
        <textarea className="mt-1 min-h-64 w-full rounded border p-3 font-mono text-sm" value={draft} onChange={e => setDraft(e.target.value)}/>
      </label>
      <button className={button} disabled={busy || !draft.trim()} onClick={() => void run(async () => {
        await request(`/regulatory-sources/${selected}/draft`, JSON.parse(draft)); setDraft(""); setMessage("Draft saved for review.");
      })}><Save size={16}/>Save draft</button>
    </>}
    <label className="block text-sm font-medium">Review rationale
      <textarea className="mt-1 w-full rounded border p-2" value={note} onChange={e => setNote(e.target.value)}/>
    </label>
    {catalog?.reviews.map(review => <article key={review.id} className="space-y-3 border-t py-4">
      <p className="font-semibold">{review.status} · {review.regulation_id}</p>
      <blockquote className="border-l-2 pl-3 text-sm">{review.quote}</blockquote>
      <details><summary className="cursor-pointer">Proposed rule</summary><pre className="overflow-auto whitespace-pre-wrap break-words text-sm">{JSON.stringify(review.rule, null, 2)}</pre></details>
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={busy || note.trim().length < 20 || review.status === "APPROVED"} onClick={() => void run(async () => {
          await request(`/regulatory-sources/reviews/${review.id}/approve`, {note}); setMessage("Review approved. Publication is a separate step.");
        })}><Check size={16}/>Approve review</button>
        <button className={button} disabled={busy || review.status !== "APPROVED"} onClick={() => void run(async () => {
          await request(`/regulations/${review.regulation_id}/publish-version`, {}); setMessage("Published. Run impact analysis to reassess existing shipments.");
        })}><Upload size={16}/>Publish version</button>
      </div>
    </article>)}
    {message && <p role="status" className="break-words font-medium">{message}</p>}
  </section>;
}
