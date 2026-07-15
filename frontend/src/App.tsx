import { Button, Card, Input, List, Space, Table, Tabs, Tag, Upload, message } from 'antd';
import { useEffect, useState } from 'react';

const API = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';
async function get(path: string) { const r = await fetch(API + path); if (!r.ok) throw new Error(await r.text()); return r.json(); }
async function post(path: string, body?: any) { const r = await fetch(API + path, { method: 'POST', headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined }); if (!r.ok) throw new Error(await r.text()); return r.json(); }

export default function App() {
  const [docs, setDocs] = useState<any[]>([]); const [selected, setSelected] = useState<any>(); const [artifacts, setArtifacts] = useState<any>(); const [searchResults, setSearchResults] = useState<any[]>([]); const [q, setQ] = useState('機台');
  async function load(){ setDocs(await get('/documents')); }
  useEffect(()=>{ load(); },[]);
  async function upload(file:any){ const fd=new FormData(); fd.append('file', file); const r=await fetch(API+'/documents/upload',{method:'POST',body:fd}); if(!r.ok) throw new Error(await r.text()); message.success('uploaded'); await load(); return false; }
  async function process(id:string){ await post(`/documents/${id}/process`); message.success('processed'); await load(); }
  async function viewArtifacts(id:string){ setSelected(id); setArtifacts(await get(`/documents/${id}/artifacts`)); }
  async function build(id:string){ await post(`/documents/${id}/build-okf`); message.success('OKF built'); await viewArtifacts(id); await load(); }
  async function approve(id:string){ const okf = artifacts?.artifacts?.find((a:any)=>a.artifact_type==='okf_candidate')?.content_json; if(!okf){message.error('No OKF candidate'); return;} await post(`/documents/${id}/approve-okf`,{okf_json:okf,approved_by:'demo_user'}); message.success('approved'); await load(); }
  async function search(){ const r=await get(`/search?q=${encodeURIComponent(q)}`); setSearchResults(r.results); }
  return <div className="wrap"><h1>OKF Knowledge Factory MVP</h1><Tabs items={[
    {key:'docs',label:'Documents',children:<><Card className="card"><Upload beforeUpload={upload} showUploadList={false}><Button>Upload local file</Button></Upload><Button onClick={load} style={{marginLeft:8}}>Refresh</Button></Card><Table rowKey="document_id" dataSource={docs} columns={[{title:'File',dataIndex:'file_name'},{title:'Type',dataIndex:'file_type'},{title:'Status',dataIndex:'status',render:(s)=><Tag>{s}</Tag>},{title:'Actions',render:(_:any,d:any)=><Space wrap><Button onClick={()=>process(d.document_id)}>Process</Button><Button onClick={()=>viewArtifacts(d.document_id)}>Artifacts</Button><Button onClick={()=>build(d.document_id)}>Build OKF</Button><Button type="primary" onClick={()=>approve(d.document_id)}>Approve latest OKF</Button></Space>}]} /></>},
    {key:'artifacts',label:'Artifacts',children:<Card title={selected || 'Select a document'}><pre>{JSON.stringify(artifacts,null,2)}</pre></Card>},
    {key:'search',label:'Search',children:<Card><Space.Compact style={{width:'100%',marginBottom:16}}><Input value={q} onChange={e=>setQ(e.target.value)} onPressEnter={search}/><Button type="primary" onClick={search}>Search</Button></Space.Compact><List dataSource={searchResults} renderItem={(r:any)=><List.Item><List.Item.Meta title={<Space><span>{r.title}</span><Tag>{r.chunk_type}</Tag><Tag>{Number(r.score||0).toFixed(3)}</Tag></Space>} description={<pre>{r.content}</pre>}/></List.Item>}/></Card>}
  ]}/></div>;
}
