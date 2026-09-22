#!/usr/bin/env python3
"""Read-only fixture/HTML contract checker; does not implement the product."""
from pathlib import Path
from html.parser import HTMLParser
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FROZEN = '33f85f2656a561534f875ee5e690a4233d95aec6'
HTML = ROOT / 'app/static/index.html'
checks = []

def check(label, condition):
    assert condition, label
    checks.append(label)

class Structure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

html = HTML.read_text()
check('HTML has no trailing whitespace', all(line == line.rstrip() for line in html.splitlines()))
parsed = Structure()
parsed.feed(html)
data_match = re.search(r'<script id="fixture-data" type="application/json">(.*?)</script>', html, re.S)
check('embedded data block exists', data_match is not None)
data = json.loads(data_match[1])
check('approved baseline exact', data['approved_commit'] == FROZEN)
for path, digest in data['source_sha256'].items():
    current = (ROOT / path).read_bytes()
    approved = subprocess.check_output(['git', 'show', FROZEN + ':' + path], cwd=ROOT)
    check('frozen bytes and digest: ' + path, current == approved and hashlib.sha256(current).hexdigest() == digest)
source = lambda path: json.loads((ROOT / path).read_text())
cases = {c['id']: c for c in source('fixtures/G2-acceptance-cases.json')['cases']}
invalid = {c['id']: c for c in source('fixtures/G2-invalid-input-cases.json')['cases']}
primary = source('fixtures/G2-expected-results.json')
check('primary oracle identical', data['originals'] == {'fixtures/G2-expected-results.json': primary})
required = {'G2-AC-01','G2-AC-02','G2-AC-03','G2-AC-04','G2-AC-12A','G2-AC-12E','G2-AC-05','G2-AC-06','G2-AC-14','G2-AC-07','G2-AC-08','G2-AC-09','G2-AC-10','G2-AC-11','G2-AC-18'}
check('all 15 fixed scenarios, no future gate', {s['id'] for s in data['scenarios']} == required and len(data['scenarios']) == 15)
check('three experience paths', {s['path'] for s in data['scenarios']} == {'valid','reject','boundary'})
for item in data['scenarios']:
    case = cases[item['id']]
    ref = case.get('input_file', 'fixtures/G2-acceptance-cases.json#' + item['id'])
    if item['id'] in invalid:
        expected_input = invalid[item['id']]['input']
    elif 'rows' in case:
        expected_input = case['rows']
    elif '#' in ref:
        path, fragment = ref.split('#')
        expected_input = source(path)[fragment]['canonical_rows']
    elif ref.endswith('.csv'):
        expected_input = (ROOT / ref).read_text()
    else:
        expected_input = source(ref)
    expected_oracle = case['expected']
    if item['id'] == 'G2-AC-01':
        expected_oracle = primary
    if item['id'] == 'G2-AC-18':
        near = source('fixtures/G2-near-threshold.json')
        expected_input, expected_oracle = near['rows'], near['expected']
    check('exact input/oracle/reference: ' + item['id'], item['input'] == expected_input and item['oracle'] == expected_oracle and item['source'] == ref and item['dataset_id'] == case['dataset_id'] and item['error'] == case['expected'].get('error'))
check('sample totals', primary['monthly_totals_kwh'] == {'2026-01':'300.000','2026-02':'370.000'})
check('A anomaly and B normal', primary['building_comparisons']['2026-02/A']['percent_change'] == '60.000' and primary['building_comparisons']['2026-02/A']['anomaly'] is True and primary['building_comparisons']['2026-02/B']['percent_change'] == '5.000' and primary['building_comparisons']['2026-02/B']['anomaly'] is False)
ids = [attrs['id'] for _, attrs in parsed.elements if 'id' in attrs]
check('unique DOM IDs', len(ids) == len(set(ids)))
check('native select labelled', any(tag == 'label' and attrs.get('for') == 'case' for tag, attrs in parsed.elements) and any(tag == 'select' and attrs.get('id') == 'case' for tag, attrs in parsed.elements))
check('native buttons for three paths', len([1 for tag, attrs in parsed.elements if tag == 'button' and 'data-path' in attrs]) == 3)
check('result initially hidden', any(attrs.get('id') == 'result' and 'hidden' in attrs for _, attrs in parsed.elements))
check('announced status', any(attrs.get('role') == 'status' and attrs.get('aria-live') == 'polite' for _, attrs in parsed.elements))
check('no external asset attributes', not any(key in attrs for _, attrs in parsed.elements for key in ('src','srcset')) and not any(attrs.get('href','').startswith(('http:','https:','//')) for _,attrs in parsed.elements))
code = html.split('</script>')[1].split('<script>')[1]
check('no side-effect APIs or engine arithmetic', re.search(r'\b(fetch|XMLHttpRequest|WebSocket|localStorage|sessionStorage|indexedDB|Worker|sendBeacon|parseFloat|eval)\b|innerHTML|document\.write', code) is None)
check('no future result encoded', 'G2-70PCT-R1' not in html and 'G2-AC-15' not in html)
for marker in ['simulated','ROUND_HALF_EVEN','NOT_PROVEN','NO_PRIOR_MONTH','ZERO_BASELINE','&gt;30.000','@media(max-width:650px)',':focus-visible','noscript','connect-src \'none\'']:
    check('required boundary/accessibility marker: ' + marker, marker in html)
# Actual token contrast arithmetic, independent from any browser rendering.
def luminance(color):
    rgb = [int(color[i:i+2],16)/255 for i in (1,3,5)]
    rgb = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in rgb]
    return sum(v*w for v,w in zip(rgb,(.2126,.7152,.0722)))
for foreground, background in [('#162d3d','#ffffff'),('#42586b','#f1f5f8'),('#ffffff','#1559a5'),('#8d301e','#ffffff')]:
    a,b=sorted([luminance(foreground),luminance(background)])
    check('text contrast >= 4.5: '+foreground+'/'+background,(b+.05)/(a+.05)>=4.5)
# Parse JavaScript with the installed runtime without evaluating DOM or sending requests.
subprocess.run(['node','--check'],input=code.encode(),check=True,capture_output=True)
check('JavaScript syntax', True)
# Exercise view transitions with a tiny in-memory DOM stub: no browser/network.
# This checks event wiring and stale-result clearing, not layout or native controls.
harness = r"""
const assert = require('assert');
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.attrs={};this.dataset={};this.textContent='';this.value='';this.hidden=false;this.events={};}
  replaceChildren(...children){this.children=children;if(this.tag==='select')this.value='';}
  append(child){this.children.push(child);if(this.tag==='select' && this.children.length===1)this.value=child.value;}
  setAttribute(key,value){this.attrs[key]=value;}
  addEventListener(key,fn){this.events[key]=fn;}
  get lastElementChild(){return this.children[this.children.length-1];}
}
const elements=Object.fromEntries(IDS.map(id=>[id,new Element(id==='case'?'select':'div')]));
elements['fixture-data'].textContent=JSON.stringify(DATA);
const pathButtons=['valid','reject','boundary'].map(path=>{const e=new Element('button');e.dataset.path=path;return e;});
const document={getElementById:id=>elements[id],querySelectorAll:()=>pathButtons,createElement:tag=>new Element(tag)};
"""
interaction = r"""
assert.equal(elements.result.hidden,true);
let exercised=0;
for(const path of ['valid','reject','boundary']){
  pathButtons.find(b=>b.dataset.path===path).events.click();
  assert.equal(pathButtons.filter(b=>b.attrs['aria-pressed']==='true').length,1);
  for(const item of DATA.scenarios.filter(s=>s.path===path)){
    elements.case.value=item.id;
    elements.case.events.change();
    assert.equal(elements.result.hidden,true);
    assert.equal(elements.oracle.textContent,'');
    elements.show.events.click();
    assert.equal(elements.result.hidden,false);
    assert.equal(elements.oracle.textContent,JSON.stringify(item.oracle,null,2));
    assert.equal(elements.outcome.children[0].textContent,item.summary);
    assert.ok(elements.source.textContent.includes(item.dataset_id));
    if(item.error)assert.ok(elements.state.textContent.includes('NONE'));
    if(item.id==='G2-AC-01'){
      assert.equal(elements.comparisons.children.length,4);
      assert.equal(elements.comparisons.children[2].children[2].textContent,'60.000%');
      assert.equal(elements.comparisons.children[3].children[2].textContent,'5.000%');
      assert.equal(elements.comparisons.children[0].children[2].textContent,'—（null）');
    }else{assert.equal(elements['primary-result'].hidden,true);}
    exercised++;
  }
}
assert.equal(exercised,15);
console.log('15 DOM-stub scenarios PASS; real browser NOT_RUN');
"""
node_input = 'const IDS='+json.dumps(ids)+';const DATA='+json.dumps(data)+';\n'+harness+code+interaction
subprocess.run(['node'],input=node_input.encode(),check=True,capture_output=True)
check('15 DOM-stub interactions and stale result clearing (not browser)', True)
result = {'schema':'factory-s4-g3-static-check/v0.1','status':'PASS','approved_g2_commit':FROZEN,'html_sha256':hashlib.sha256(HTML.read_bytes()).hexdigest(),'checks_passed':len(checks),'checks':checks,'proof_boundary':'Static fixture/structure/contrast/syntax plus 15 in-memory DOM-stub transitions only. Browser file URL rejected by tool security policy; actual browser layout/keyboard NOT_RUN. Not product engine, persistence, security, independent review, or Gate approval.'}
print(json.dumps(result,ensure_ascii=False,indent=2))
