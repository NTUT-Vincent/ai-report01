import { Alert, Button, Card, Input, List, Space, Table, Tabs, Tag, Upload, message } from 'antd';
import { useEffect, useState } from 'react';

const API = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

async function get(path: string) {
  const response = await fetch(API + path);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function post(path: string, body?: unknown) {
  const response = await fetch(API + path, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export default function App() {
  const [docs, setDocs] = useState<any[]>([]);
  const [selected, setSelected] = useState<string>();
  const [artifacts, setArtifacts] = useState<any>();
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [q, setQ] = useState('機台');
  const [baseUrl, setBaseUrl] = useState('http://localhost:8000/v1');
  const [model, setModel] = useState('local-model');
  const [apiKey, setApiKey] = useState('');

  const agentPayload = () => ({
    agent: {
      base_url: baseUrl,
      model,
      api_key: apiKey,
      temperature: 0,
      timeout_seconds: 120,
      use_response_format: false,
    },
  });

  async function load() {
    setDocs(await get('/documents'));
  }

  useEffect(() => {
    load().catch((error) => message.error(String(error)));
  }, []);

  async function upload(file: File) {
    try {
      const form = new FormData();
      form.append('file', file);
      const response = await fetch(API + '/documents/upload', { method: 'POST', body: form });
      if (!response.ok) throw new Error(await response.text());
      message.success('uploaded');
      await load();
    } catch (error) {
      message.error(`Upload failed: ${String(error)}`);
    }
    return false;
  }

  function connectionReady() {
    if (!model || !apiKey || !baseUrl) {
      message.error('Please enter base URL, model, and API key');
      return false;
    }
    return true;
  }

  async function process(id: string) {
    if (!connectionReady()) return;
    try {
      await post(`/documents/${id}/process`, agentPayload());
      message.success('processed by real agents');
      await load();
    } catch (error) {
      message.error(`Process failed: ${String(error)}`);
      await load();
    }
  }

  async function viewArtifacts(id: string) {
    try {
      setSelected(id);
      setArtifacts(await get(`/documents/${id}/artifacts`));
    } catch (error) {
      message.error(`Artifacts failed: ${String(error)}`);
    }
  }

  async function build(id: string) {
    if (!connectionReady()) return;
    try {
      await post(`/documents/${id}/build-okf`, agentPayload());
      message.success('OKF built by agent');
      await viewArtifacts(id);
      await load();
    } catch (error) {
      message.error(`Build failed: ${String(error)}`);
      await load();
    }
  }

  async function approve(id: string) {
    const okf = artifacts?.artifacts?.find((artifact: any) => artifact.artifact_type === 'okf_candidate')?.content_json;
    if (!okf) {
      message.error('No OKF candidate');
      return;
    }
    try {
      await post(`/documents/${id}/approve-okf`, { okf_json: okf, approved_by: 'demo_user' });
      message.success('approved');
      await load();
    } catch (error) {
      message.error(`Approve failed: ${String(error)}`);
    }
  }

  async function search() {
    try {
      const result = await get(`/search?q=${encodeURIComponent(q)}`);
      setSearchResults(result.results);
    } catch (error) {
      message.error(`Search failed: ${String(error)}`);
    }
  }

  const connectionCard = (
    <Card title="OpenAI-compatible Agent Connection" className="card">
      <Alert
        type="info"
        showIcon
        message="The API key is kept only in this page's memory and sent in the process/build request. It is not written to the project database by the backend."
        style={{ marginBottom: 12 }}
      />
      <Space direction="vertical" style={{ width: '100%' }}>
        <Input data-testid="base-url" addonBefore="Base URL" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        <Input data-testid="model-name" addonBefore="Model" value={model} onChange={(e) => setModel(e.target.value)} />
        <Input.Password data-testid="api-key" addonBefore="API Key" value={apiKey} onChange={(e) => setApiKey(e.target.value)} autoComplete="off" />
      </Space>
    </Card>
  );

  return (
    <div className="wrap">
      <h1>OKF Knowledge Factory MVP</h1>
      <Tabs
        items={[
          {
            key: 'docs',
            label: 'Documents',
            children: (
              <>
                {connectionCard}
                <Card className="card">
                  <Upload beforeUpload={upload} showUploadList={false}>
                    <Button data-testid="upload-button">Upload local file</Button>
                  </Upload>
                  <Button onClick={() => load().catch((error) => message.error(String(error)))} style={{ marginLeft: 8 }}>Refresh</Button>
                </Card>
                <Table
                  rowKey="document_id"
                  dataSource={docs}
                  columns={[
                    { title: 'File', dataIndex: 'file_name' },
                    { title: 'Type', dataIndex: 'file_type' },
                    { title: 'Status', dataIndex: 'status', render: (status) => <Tag>{status}</Tag> },
                    {
                      title: 'Actions',
                      render: (_: unknown, document: any) => (
                        <Space wrap>
                          <Button data-testid={`process-${document.document_id}`} onClick={() => process(document.document_id)}>Process with Agents</Button>
                          <Button onClick={() => viewArtifacts(document.document_id)}>Artifacts</Button>
                          <Button data-testid={`build-${document.document_id}`} onClick={() => build(document.document_id)}>Build OKF with Agent</Button>
                          <Button data-testid={`approve-${document.document_id}`} type="primary" onClick={() => approve(document.document_id)}>Approve latest OKF</Button>
                        </Space>
                      ),
                    },
                  ]}
                />
              </>
            ),
          },
          {
            key: 'artifacts',
            label: 'Artifacts',
            children: <Card title={selected || 'Select a document'}><pre>{JSON.stringify(artifacts, null, 2)}</pre></Card>,
          },
          {
            key: 'search',
            label: 'Search',
            children: (
              <Card>
                <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
                  <Input data-testid="search-input" value={q} onChange={(e) => setQ(e.target.value)} onPressEnter={search} />
                  <Button data-testid="search-button" type="primary" onClick={search}>Search</Button>
                </Space.Compact>
                <List
                  data-testid="search-results"
                  dataSource={searchResults}
                  renderItem={(result: any) => (
                    <List.Item>
                      <List.Item.Meta
                        title={<Space><span>{result.title}</span><Tag>{result.chunk_type}</Tag><Tag>{Number(result.score || 0).toFixed(3)}</Tag></Space>}
                        description={<pre>{result.content}</pre>}
                      />
                    </List.Item>
                  )}
                />
              </Card>
            ),
          },
        ]}
      />
    </div>
  );
}
