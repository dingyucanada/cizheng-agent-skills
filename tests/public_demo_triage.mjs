import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
const html=await readFile(new URL('../site/triage.html',import.meta.url),'utf8');
const script=await readFile(new URL('../site/triage.js',import.meta.url),'utf8');
function fresh(){const dom=new JSDOM(html,{url:'https://example.test/triage.html',runScripts:'outside-only'});dom.window.fetch=()=>{throw Error('Teaching rules must not call any external model')};dom.window.eval(script);return dom;}
function values(dom){const d=dom.window.document;return ['conflict','priority','coverage'].map(id=>d.getElementById(id).textContent);}
function input(dom,id,value){const e=dom.window.document.getElementById(id);e.value=String(value);e.dispatchEvent(new dom.window.Event('input',{bubbles:true}));}
test('all unknown material gives no conflict estimate and zero coverage',()=>{const dom=fresh();try{dom.window.document.querySelector('[data-preset=unknown]').click();assert.deepEqual(values(dom),['未评','50','0%']);assert.match(dom.window.document.getElementById('alerts').textContent,/不能当作/);}finally{dom.window.close();}});
test('independent date and size contradictions add fixed dimension weights without a fake probability',()=>{const dom=fresh();try{dom.window.document.querySelector('[data-preset=combined]').click();assert.deepEqual(values(dom),['35','67.5','35%']);assert.equal(dom.window.document.querySelectorAll('#alerts article').length,2);}finally{dom.window.close();}});
test('an invalid date interval cannot hide a valid independent size contradiction',()=>{const dom=fresh();try{dom.window.document.querySelector('[data-preset=combined]').click();input(dom,'production-min',1900);assert.deepEqual(values(dom),['15','57.5','15%']);assert.match(dom.window.document.getElementById('input-status').textContent,/起年/);}finally{dom.window.close();}});
test('intervals sharing an endpoint are not disjoint and do not imply professional consistency',()=>{const dom=fresh();try{input(dom,'height-b-min',301);input(dom,'height-b-max',302);assert.deepEqual(values(dom),['未评','50','0%']);assert.match(dom.window.document.getElementById('dimensions').textContent,/未知/);}finally{dom.window.close();}});
