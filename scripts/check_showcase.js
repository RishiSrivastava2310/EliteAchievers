// Offline interaction logic checks for the generated report. No browser or network.
"use strict";
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");
const root = path.resolve(__dirname,"..");
const html = fs.readFileSync(path.join(root,"reports","judge_showcase.html"),"utf8");
const packed = html.match(/<script type="application\/json" id="data">([\s\S]*?)<\/script>/)[1];
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const data = JSON.parse(packed);
class Element {
  constructor(){this.children=[];this.dataset={};this.attrs={};this.handlers={};this.textContent="";this.checked=false;this.value="0";}
  setAttribute(k,v){this.attrs[k]=v;}
  appendChild(child){this.children.push(child);}
  addEventListener(type,fn){this.handlers[type]=fn;}
}
const nodes = {};
for(const m of html.matchAll(/\bid="([^"]+)"/g))nodes[m[1]]=new Element();
nodes.data.textContent=packed;
nodes.outcome.checked=true;
const context=vm.createContext({
  document:{getElementById:id=>{assert.ok(nodes[id],"Missing element: "+id);return nodes[id];},
            createElement:()=>new Element()},
  window:{print(){},handlers:{},addEventListener(type,fn){this.handlers[type]=fn;}},console,URLSearchParams,location:{hash:""}
});
vm.runInContext(script,context);
assert.equal(nodes.risk.textContent,"46.9%");
assert.equal(nodes.lead.textContent,"18.35 hours");
assert.equal(nodes.status.textContent,"Warning raised");
let states=0,plots=0;
for(let c=0;c<data.cases.length;c++){
  vm.runInContext("choose("+c+")",context);
  for(let i=0;i<data.cases[c].frames.length;i++){
    for(const reveal of [true,false]){
      nodes.replay.value=String(i);nodes.outcome.checked=reveal;
      nodes.replay.handlers.input();
      const f=data.cases[c].frames[i];
      assert.equal(nodes.chart.src,f.plots[String(reveal&&data.cases[c].kind==="patient")]);
      assert.ok(nodes.chart.src.startsWith("data:image/svg+xml;base64,"));
      const svg=Buffer.from(nodes.chart.src.split(",")[1],"base64").toString("utf8");
      assert.ok(svg.includes("<svg") && (svg.match(/<path/g)||[]).length>5);
      for(const [id,node]of Object.entries(nodes)){
        if(id==="data")continue;
        assert.ok(!/undefined|NaN|gemini|api key/i.test(node.textContent),"Invalid display text in "+id);
      }
      assert.equal(nodes.risk.textContent,f.risk===null?"Not scored":f.risk.toFixed(1)+"%");
      if(data.cases[c].kind!=="patient")assert.equal(nodes.lead.textContent,"Illustrative");
      else if(reveal&&f.followup_status==="no_injury_recorded")assert.equal(nodes.lead.textContent,"None in 24 hours");
      else if(reveal&&f.followup_status==="incomplete_followup")assert.equal(nodes.lead.textContent,"Follow-up incomplete");
      else if(!reveal)assert.equal(nodes.lead.textContent,"Not revealed");
      states++;plots++;
    }
  }
}
vm.runInContext("choose("+data.cases.findIndex(c=>c.id==="stable")+")",context);
assert.equal(nodes.risk.textContent,"8.9%");
assert.equal(nodes.status.textContent,"No warning raised");
vm.runInContext("choose("+data.cases.findIndex(c=>c.id==="concerning_trend")+")",context);
assert.equal(nodes.risk.textContent,"45.8%");
assert.equal(nodes.status.textContent,"Warning raised");
vm.runInContext("choose(0)",context);
nodes.outcome.checked=false;nodes.outcome.handlers.change();
assert.equal(nodes.lead.textContent,"Not revealed");
vm.runInContext("choose(0)",context);
const patients=data.cases.filter(c=>c.kind==="patient");
assert.equal(patients.length,15);
assert.equal(new Set(patients.map(c=>c.patient_id)).size,15);
assert.equal(new Set(patients.map(c=>c.pattern)).size,4);
assert.equal(nodes.patientPosition.textContent,"Patient 1 of 15");
const firstChart=nodes.chart.src;
for(let i=1;i<patients.length;i++){
  nodes.nextPatient.handlers.click();
  assert.equal(nodes.patientPosition.textContent,"Patient "+(i+1)+" of 15");
  const c=patients[i], f=c.frames[c.default_index];
  assert.equal(nodes.explanation.textContent,f.explanation);
  assert.equal(nodes.risk.textContent,f.risk.toFixed(1)+"%");
  assert.notEqual(nodes.chart.src,firstChart);
}
nodes.nextPatient.handlers.click();
assert.equal(nodes.patientPosition.textContent,"Patient 1 of 15");
nodes.previousPatient.handlers.click();
assert.equal(nodes.patientPosition.textContent,"Patient 15 of 15");
context.location.hash="#patient=patient_2";
context.window.handlers.hashchange();
assert.equal(nodes.patientPosition.textContent,"Patient 2 of 15");
context.location.hash="#patient=unknown";
context.window.handlers.hashchange();
assert.equal(nodes.patientPosition.textContent,"Patient 1 of 15");
vm.runInContext(script,vm.createContext({
  document:context.document,window:context.window,console,URLSearchParams,
  location:{hash:"#patient=patient_2"}
}));
assert.equal(nodes.patientPosition.textContent,"Patient 2 of 15");
const report={
  status:"passed",model_sha256:data.model_sha256,
  render_states_checked:states,embedded_graphs_checked:plots,
  scope:"Offline chart-data, SVG and DOM event-logic checks; rendered plot preview inspected separately.",
  real_selected_warning_lead_hours:18.35,
  real_patient_count:patients.length,
  scenario_types_checked:[...new Set(patients.map(c=>c.pattern))],
  patient_navigation_checked:true,
  patient_deep_link_checked:true,
  provider_branding_in_display:false,
  external_chart_requests_required:false
};
fs.writeFileSync(path.join(root,"reports","showcase_verification.json"),JSON.stringify(report,null,2)+"\n");
console.log(JSON.stringify(report,null,2));
