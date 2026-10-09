"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Plus, Trash2, RefreshCw, Save, GitCompareArrows } from "lucide-react";
import { apiFetch, Shipment, IndianLocation } from "@/lib/shipments";
import { complianceApiBaseUrl } from "@/lib/compliance";

type Place = IndianLocation & {longitude?: number; latitude?: number};
type Option = {offer_id:string; carrier:string; reference:string; quoted_price_inr:number; duration_hours:number;
  generalized_cost_inr:number; blocking_reasons:string[]; source_url:string; source_reference:string;
  valid_until:string; explanation:string; historical_hours:number|null; eligible:boolean;
  compliance:{status:string; missing_documents:string[]; applicable_rules:{rule_id:string;version:string;source_url:string;title:string}[]}};
type RecordRow = {id:string;kind:string;recorded_at:string;carrier?:string;reference?:string;source_url?:string;
  total_price_inr?:number;valid_until?:string; options?:Option[];recommended_offer_id?:string|null;inputs_changed?:boolean;
  previous_decision_id?:string;input_fingerprint?:string;unknown_factors?:string[];scope?:string};
type Memory = {records:RecordRow[];corridors:Record<string,{sample_count:number;median_hours:number}>;routing_configured:boolean;catalog_mode:string};
const button = "inline-flex items-center justify-center gap-2 rounded border px-3 py-2 text-sm font-medium disabled:opacity-50";
const input = "mt-1 block w-full min-w-0 rounded border bg-white p-2 text-sm";

export default function RouteMemory({shipmentId}:{shipmentId:string}) {
  const [shipment,setShipment]=useState<Shipment|null>(null);
  const [memory,setMemory]=useState<Memory|null>(null);
  const [places,setPlaces]=useState<Place[]>([]);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const [timeValue,setTimeValue]=useState(0);
  const [useHistory,setUseHistory]=useState(true);
  const [autoRefresh,setAutoRefresh]=useState(true);
  const [selected,setSelected]=useState("");
  const [form,setForm]=useState({carrier:"",reference:"",total_price_inr:"",duration_hours:"",source_url:"",source_reference:"",review_note:"",valid_until:"",observed_at:"",coverage_confirmed:false});
  const [vehicle,setVehicle]=useState({weight:"",height:"",width:"",length:"",axleload:"",hazmat:false});
  const request=useCallback(async(path:string,body?:unknown)=>{
    const response=await fetch(`${complianceApiBaseUrl}/state-relations/${shipmentId}${path}`, body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok) throw new Error(typeof data.detail==="string"?data.detail:"Check required fields, route stops and administrator permissions.");
    return data;
  },[shipmentId]);
  const refresh=useCallback(async()=>setMemory(await request("")),[request]);
  useEffect(()=>{
    if(!autoRefresh||busy) return;
    const timer=setInterval(()=>{void (async()=>{
      setBusy(true);
      try { await request("/observe",{}); if(memory?.records.some(r=>r.kind==="OFFER")) await request("/evaluate",{value_of_time_inr_per_hour:timeValue,use_observed_history:useHistory}); await refresh(); }
      catch(e){setMessage(e instanceof Error?e.message:"Automatic refresh failed");}
      finally{setBusy(false);}
    })();},60000);
    return ()=>clearInterval(timer);
  },[autoRefresh,busy,memory,refresh,request,timeValue,useHistory]);
  useEffect(()=>{void apiFetch<Shipment>(`/shipments/${shipmentId}`).then(s=>{setShipment(s);if(s.domestic)setPlaces([s.domestic.origin,...[...s.route_legs].sort((a,b)=>a.sequence_number-b.sequence_number).map(l=>l.domestic!.destination)]);}).catch(e=>setMessage(String(e)));void refresh().catch(e=>setMessage(String(e)));},[shipmentId,refresh]);
  async function run(action:()=>Promise<void>){setBusy(true);setMessage("");try{await action();await refresh();}catch(e){setMessage(e instanceof Error?e.message:"Request failed");}finally{setBusy(false);}}
  const decisions=memory?.records.filter(r=>r.kind==="DECISION")??[];
  const decision=decisions.find(r=>r.id===selected)??decisions[0];
  const offers=memory?.records.filter(r=>r.kind==="OFFER")??[];
  function placeValue(index:number,key:keyof Place,value:string){setPlaces(old=>old.map((p,i)=>i===index?{...p,[key]:["latitude","longitude"].includes(key)?(value===""?undefined:Number(value)):value}:p));}
  if(!shipment) return <main className="p-6" role="status">{message||"Loading shipment..."}</main>;
  if(!shipment.domestic) return <main className="space-y-4 p-6"><Link href={`/shipments/${shipmentId}#optimizer`} className="underline">Shipment route options</Link><p>Route memory currently supports domestic Indian road shipments.</p></main>;
  return <main className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
    <Link href={`/shipments/${shipmentId}#optimizer`} className="inline-flex items-center gap-2 text-sm"><ArrowLeft size={16}/>Shipment</Link>
    <header className="flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-2xl font-semibold">Route memory and decisions</h1><p className="mt-1">{shipment?.shipment_reference}</p></div><button className={button} disabled={busy} onClick={()=>void run(async()=>{await request("/observe",{});setMessage("Shipment event history updated.");})}><RefreshCw size={16}/>Sync movement history</button></header>
    <p className="border-l-4 border-teal-600 pl-3 text-sm">{memory?.catalog_mode==="reviewed"?"Reviewed catalog":"Demo catalog: booking recommendations disabled"}. Carrier offers are reviewer-entered, not live market prices. Estimates are not a booking or legal guarantee.</p>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={autoRefresh} onChange={e=>setAutoRefresh(e.target.checked)}/>Monitor this shipment every minute while open</label>
    {message&&<p role="status" className="break-words font-medium">{message}</p>}
    <section className="space-y-4 border-t pt-5"><h2 className="text-lg font-semibold">Observed corridor history</h2>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-2">PIN-to-PIN corridor</th><th className="p-2">Observations</th><th className="p-2">Median travel hours</th></tr></thead><tbody>{Object.entries(memory?.corridors??{}).map(([key,v])=><tr key={key} className="border-t"><td className="p-2">{key.replace(":"," to ")}</td><td className="p-2">{v.sample_count}</td><td className="p-2">{v.median_hours}</td></tr>)}</tbody></table></div>
      {!Object.keys(memory?.corridors??{}).length&&<p className="text-sm">No paired shipment-level loading and arrival observations recorded.</p>}
    </section>
    <section className="space-y-4 border-t pt-5"><h2 className="text-lg font-semibold">Carrier offers</h2>
      {offers.map(o=><div key={o.id} className="flex flex-wrap items-center justify-between gap-3 border-b py-3"><div><p className="font-medium">{o.carrier} · {o.reference}</p><p className="text-sm">INR {o.total_price_inr?.toLocaleString("en-IN")} · Valid until {o.valid_until?new Date(o.valid_until).toLocaleString():"Unknown"}</p></div><button className={button} disabled={busy||!memory?.routing_configured} onClick={()=>void run(async()=>{await request(`/offers/${o.id}/refresh-routing`,{});setMessage("Truck routing snapshot updated. Recompare offers to use it.");})}><RefreshCw size={16}/>Refresh truck route</button></div>)}
      {!memory?.routing_configured&&<p className="text-sm">External truck routing is not configured. Carrier duration estimates remain available.</p>}
      <details><summary className="cursor-pointer font-semibold">Add reviewed carrier offer</summary><form className="mt-4 space-y-4" onSubmit={e=>{e.preventDefault();void run(async()=>{
        const numericVehicle=Object.fromEntries(Object.entries(vehicle).map(([k,v])=>[k,k==="hazmat"?v:Number(v)]));
        await request("/offers",{...form,total_price_inr:Number(form.total_price_inr),duration_hours:Number(form.duration_hours),observed_at:new Date(form.observed_at).toISOString(),valid_until:new Date(form.valid_until).toISOString(),places,vehicle:numericVehicle,all_inclusive:true});setMessage("Versioned offer saved. Earlier offers remain in history.");
      });}}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{([['carrier','Carrier','text'],['reference','Quote reference','text'],['total_price_inr','All-inclusive price (INR)','number'],['duration_hours','Carrier duration (hours)','number'],['observed_at','Quote observed at','datetime-local'],['valid_until','Valid until departure / booking','datetime-local'],['source_url','Quote source URL','url'],['source_reference','Source document reference','text']] as const).map(([key,label,type])=><label key={key} className="text-sm font-medium">{label}<input className={input} required type={type} min={type==="number"?"0.01":undefined} step="any" value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}</div>
        <fieldset className="space-y-3"><legend className="font-medium">Route stops</legend>{places.map((place,i)=><div key={i} className="grid grid-cols-2 items-end gap-3 border-b pb-3 md:grid-cols-6">{([['state','State'],['city','City'],['pincode','PIN code'],['longitude','Longitude'],['latitude','Latitude']] as const).map(([key,label])=><label key={key} className="min-w-0 text-sm">{label}<input aria-label={`Stop ${i+1} ${label}`} className={input} required={!["longitude","latitude"].includes(key)} value={place[key]??""} type={["longitude","latitude"].includes(key)?"number":"text"} step="any" onChange={e=>placeValue(i,key,e.target.value)}/></label>)}<button type="button" className={button} title="Remove stop" aria-label={`Remove stop ${i+1}`} disabled={places.length<=2} onClick={()=>setPlaces(places.filter((_,j)=>j!==i))}><Trash2 size={16}/></button></div>)}<button type="button" className={button} onClick={()=>setPlaces([...places.slice(0,-1),{state:"",city:"",pincode:""},places[places.length-1]])}><Plus size={16}/>Add intermediate stop</button></fieldset>
        <fieldset><legend className="mb-3 font-medium">Quoted vehicle</legend><div className="grid grid-cols-2 gap-3 md:grid-cols-5">{([['weight','Gross weight (tonnes)'],['height','Height (m)'],['width','Width (m)'],['length','Length (m)'],['axleload','Axle load (tonnes)']] as const).map(([key,label])=><label key={key} className="text-sm">{label}<input className={input} required type="number" min="0.01" step="any" value={vehicle[key]} onChange={e=>setVehicle({...vehicle,[key]:e.target.value})}/></label>)}</div><label className="mt-3 flex gap-2 text-sm"><input type="checkbox" checked={vehicle.hazmat} onChange={e=>setVehicle({...vehicle,hazmat:e.target.checked})}/>Hazardous goods</label></fieldset>
        <label className="block text-sm font-medium">Review rationale<textarea className={input} minLength={20} required value={form.review_note} onChange={e=>setForm({...form,review_note:e.target.value})}/></label>
        <label className="flex items-start gap-2 text-sm"><input className="mt-1" type="checkbox" checked={form.coverage_confirmed} onChange={e=>setForm({...form,coverage_confirmed:e.target.checked})}/>Carrier capacity, route restrictions and all charges (fuel, tolls, tax and handling) have been reviewed for this shipment.</label>
        <button className={button} disabled={busy}><Save size={16}/>Save offer version</button>
      </form></details>
    </section>
    <section className="space-y-4 border-t pt-5"><div className="flex flex-wrap items-end gap-4"><label className="text-sm font-medium">Value of time (INR/hour)<input className={input} type="number" min="0" max="1000000" value={timeValue} onChange={e=>setTimeValue(Number(e.target.value))}/></label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={useHistory} onChange={e=>setUseHistory(e.target.checked)}/>Consider recent observed durations</label><button className={button} disabled={busy} onClick={()=>void run(async()=>{const result=await request("/evaluate",{value_of_time_inr_per_hour:timeValue,use_observed_history:useHistory});setSelected(result.id);})}><GitCompareArrows size={16}/>Compare current offers</button></div>
      <label className="block text-sm font-medium">Decision history<select className={input} value={decision?.id??""} onChange={e=>setSelected(e.target.value)}><option value="">No saved decision</option>{decisions.map(d=><option key={d.id} value={d.id}>{new Date(d.recorded_at).toLocaleString()} · {d.inputs_changed?"Inputs changed":"Same inputs"}</option>)}</select></label>
      {decision&&<><p className="font-medium">{decision.recommended_offer_id?"Best-supported offer identified":"No booking-ready offer"}</p><p className="text-sm">{decision.scope}</p><p className="text-sm">Unresolved live factors: {decision.unknown_factors?.join(", ")}</p>{decision.options?.map(o=><article key={o.offer_id} className="space-y-2 border-t py-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{o.carrier} · {o.reference}</h3><span className="font-medium">{decision.recommended_offer_id===o.offer_id?"Recommended":o.eligible?"Eligible":"Review required"}</span></div><p>INR {o.quoted_price_inr.toLocaleString("en-IN")} · {o.duration_hours} h · Time-adjusted cost INR {o.generalized_cost_inr.toLocaleString("en-IN")}</p><p className="text-sm">{o.explanation}</p><a className="break-all text-sm underline" href={o.source_url} target="_blank" rel="noopener noreferrer">{o.source_reference}</a><ul className="list-disc space-y-1 pl-5 text-sm">{o.blocking_reasons.map((r,i)=><li key={i}>{r}</li>)}</ul><details><summary className="cursor-pointer text-sm">Compliance evidence: {o.compliance.status}</summary><ul className="space-y-1 text-sm">{o.compliance.applicable_rules.map((r,i)=><li key={i}><a href={r.source_url} target="_blank" rel="noopener noreferrer" className="underline">{r.title} ({r.version})</a></li>)}</ul><p>Missing documents: {o.compliance.missing_documents.join(", ")||"None in evaluated rules"}</p></details></article>)}<p className="break-all text-xs">Input fingerprint: {decision.input_fingerprint}</p></>}
    </section>
  </main>;
}
