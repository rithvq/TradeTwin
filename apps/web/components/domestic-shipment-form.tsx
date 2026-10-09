"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Plus, Trash2, Sparkles, ArrowRight } from "lucide-react";
import { apiFetch, type IndianLocation, type Shipment } from "../lib/shipments";

const emptyPlace = (): IndianLocation => ({ state: "Tamil Nadu", city: "", pincode: "" });
const inputClass = "mt-1 w-full min-w-0 rounded border border-line bg-surface px-3 py-2 text-ink";
const newItem = () => ({ name: "", description: "", quantity: 1, value: 0, hs: "", stop: 0 });

export function DomesticShipmentForm() {
  const [states, setStates] = useState<string[]>([]);
  const [origin, setOrigin] = useState(emptyPlace);
  const [stops, setStops] = useState([{ ...emptyPlace(), distance: 1 }]);
  const [items, setItems] = useState([newItem()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { apiFetch<string[]>("/locations/states").then(setStates).catch(() => setError("Could not load Indian states. Refresh to try again.")); }, []);

  async function loadDemo() {
    setBusy(true); setError("");
    try { const shipment = await apiFetch<Shipment>("/demo/seed", { method: "POST" }); window.location.assign(`/shipments/${shipment.id}`); }
    catch (error) { setError(error instanceof Error ? error.message : "Could not load demo"); setBusy(false); }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      const payload = {
        shipment_reference: form.get("reference"), exporter_country: "India", importer_country: "India", transport_mode: "ROAD",
        planned_departure_at: new Date(String(form.get("departure"))).toISOString(),
        planned_arrival_at: new Date(String(form.get("arrival"))).toISOString(),
        domestic: { origin, destination: stops[stops.length-1], consignor_name: form.get("consignor"), consignee_name: form.get("consignee"), movement_reason: form.get("reason"), registered_consignor: form.get("registered") === "unknown" ? null : form.get("registered") === "yes", ordinary_goods: form.get("ordinary") === "unknown" ? null : form.get("ordinary") === "yes" },
        route_legs: stops.map((stop, index) => ({ sequence_number: index+1, origin_country: "India", destination_country: "India", transport_mode: "ROAD", carrier_name: form.get("carrier"), domestic: { origin: index ? stops[index-1] : origin, destination: stop, distance_km: stop.distance } })),
        consignments: items.map(item => ({ product_name: item.name, product_description: item.description, quantity: item.quantity, declared_value: item.value, currency: "INR", country_of_origin: "India", destination_country: "India", proposed_hs_code: item.hs || null, domestic: { destination: stops[item.stop], consignment_value: item.value } })),
      };
      const shipment = await apiFetch<Shipment>("/shipments", { method: "POST", body: JSON.stringify(payload) });
      window.location.assign(`/shipments/${shipment.id}`);
    } catch (error) { setError(error instanceof Error ? error.message : "Could not create shipment"); setBusy(false); }
  }
  function placeEditor(place: IndianLocation, change: (place: IndianLocation) => void, prefix: string) {
    return <div className="grid gap-3 sm:grid-cols-3">
      <label className="text-sm">State / UT<select aria-label={`${prefix} state`} required className={inputClass} value={place.state} onChange={event => change({ ...place, state: event.target.value })}>{states.map(state => <option key={state}>{state}</option>)}</select></label>
      <label className="text-sm">City<input aria-label={`${prefix} city`} required maxLength={100} className={inputClass} value={place.city} onChange={event => change({ ...place, city: event.target.value })} /></label>
      <label className="text-sm">PIN code<input aria-label={`${prefix} PIN code`} required pattern="[1-9][0-9]{5}" maxLength={6} inputMode="numeric" className={inputClass} value={place.pincode} onChange={event => change({ ...place, pincode: event.target.value })} /></label>
    </div>;
  }
  return <form onSubmit={submit} className="space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-semibold">Create domestic shipment</h2><button disabled={busy} type="button" onClick={() => void loadDemo()} className="flex items-center gap-2 text-sm font-semibold text-accent"><Sparkles size={16} />Load demo scenario</button></div>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="text-sm">Shipment reference<input name="reference" required maxLength={80} className={inputClass} /></label>
      <label className="text-sm">Road carrier<input name="carrier" required className={inputClass} /></label>
      <label className="text-sm">Consignor<input name="consignor" required maxLength={120} className={inputClass} /></label>
      <label className="text-sm">Consignee<input name="consignee" required maxLength={120} className={inputClass} /></label>
      <label className="text-sm">Planned departure<input name="departure" type="datetime-local" required className={inputClass} /></label>
      <label className="text-sm">Planned arrival<input name="arrival" type="datetime-local" required className={inputClass} /></label>
      <label className="text-sm">Movement purpose<select aria-label="Movement purpose" name="reason" className={inputClass}><option value="SUPPLY">Supply</option><option value="JOB_WORK">Job work</option><option value="STOCK_TRANSFER">Stock transfer</option><option value="OTHER">Other</option></select></label>
      <label className="text-sm">GST-registered consignor<select aria-label="GST-registered consignor" name="registered" className={inputClass}><option value="unknown">Not confirmed</option><option value="yes">Yes</option><option value="no">No</option></select></label>
      <label className="text-sm sm:col-span-2">Ordinary taxable goods, with no exemptions or special handling<select aria-label="Ordinary taxable goods" name="ordinary" className={inputClass}><option value="unknown">Not confirmed</option><option value="yes">Confirmed</option><option value="no">Exempt or special goods</option></select></label>
    </div>
    <fieldset className="space-y-3 border-t border-line pt-4"><legend className="font-semibold">Dispatch location</legend>{placeEditor(origin, setOrigin, "Origin")}</fieldset>
    <fieldset className="space-y-4 border-t border-line pt-4"><legend className="font-semibold">Route stops</legend>{stops.map((stop, index) => <div key={index} className="space-y-3 border-b border-line pb-4">
      <div className="flex items-center justify-between"><span className="text-sm font-semibold">Stop {index+1}</span><button title="Remove stop" aria-label={`Remove stop ${index+1}`} type="button" disabled={stops.length===1} onClick={() => { setStops(stops.filter((_, i) => i!==index)); setItems(items.map(item => ({ ...item, stop: item.stop >= index ? Math.max(0, item.stop-1) : item.stop }))); }}><Trash2 size={16} /></button></div>
      {placeEditor(stop, place => setStops(stops.map((value, i) => i===index ? { ...place, distance: value.distance } : value)), `Stop ${index+1}`)}
      <label className="block text-sm">Distance from previous location (km)<input required type="number" min="1" max="10000" className={inputClass} value={stop.distance} onChange={event => setStops(stops.map((value, i) => i===index ? { ...value, distance: Number(event.target.value) } : value))} /></label>
    </div>)}<button type="button" className="flex items-center gap-2 text-sm font-semibold text-accent" onClick={() => setStops([...stops, { ...emptyPlace(), distance: 1 }])}><Plus size={16} />Add stop</button></fieldset>
    <fieldset className="space-y-4 border-t border-line pt-4"><legend className="font-semibold">Consignments</legend>{items.map((item, index) => <div key={index} className="space-y-3 border-b border-line pb-4">
      <div className="flex justify-between"><span className="text-sm font-semibold">Consignment {index+1}</span><button aria-label={`Remove consignment ${index+1}`} title="Remove consignment" type="button" disabled={items.length===1} onClick={() => setItems(items.filter((_, i) => i!==index))}><Trash2 size={16} /></button></div>
      <div className="grid gap-3 sm:grid-cols-2">{([['name','Product'],['description','Description'],['hs','Proposed HSN code']] as const).map(([key,label]) => <label key={key} className="text-sm">{label}<input required={key==='name'} className={inputClass} value={item[key]} onChange={event => setItems(items.map((value, i) => i===index ? { ...value, [key]: event.target.value } : value))} /></label>)}
      <label className="text-sm">Quantity<input type="number" min="1" step="1" required className={inputClass} value={item.quantity} onChange={event => setItems(items.map((value, i) => i===index ? { ...value, quantity: Number(event.target.value) } : value))} /></label>
      <label className="text-sm">Consignment value incl. tax (INR)<input type="number" min="0" max="999999999999" step="0.01" required className={inputClass} value={item.value} onChange={event => setItems(items.map((value, i) => i===index ? { ...value, value: Number(event.target.value) } : value))} /></label>
      <label className="text-sm">Delivery stop<select className={inputClass} value={item.stop} onChange={event => setItems(items.map((value, i) => i===index ? { ...value, stop: Number(event.target.value) } : value))}>{stops.map((stop,i) => <option key={i} value={i}>{i+1}. {stop.city || 'City'}, {stop.state}</option>)}</select></label></div>
    </div>)}<button className="flex items-center gap-2 text-sm font-semibold text-accent" type="button" onClick={() => setItems([...items,newItem()])}><Plus size={16} />Add consignment</button></fieldset>
    {error && <p role="alert" className="break-words text-sm text-red-700">{error}</p>}
    <button disabled={busy || !states.length} className="flex w-full items-center justify-center gap-2 rounded bg-accent px-4 py-3 font-semibold text-white disabled:opacity-50"><ArrowRight size={18}/>{busy ? 'Opening shipment...' : 'Create shipment'}</button>
  </form>;
}
