import React, { useState } from 'react';
import { Database, FileJson, FileText, ArrowRight } from 'lucide-react';
import Papa from 'papaparse';
import { XMLParser, XMLBuilder } from 'fast-xml-parser';
import TurndownService from 'turndown';
import { marked } from 'marked';

export default function DataTools() {
  const [input, setInput] = useState('');
  const [output, setOutput] = useState('');
  const [conversionType, setConversionType] = useState('json-to-csv');
  const [sqlQuery, setSqlQuery] = useState('SELECT * FROM sources LIMIT 5;');
  const [sqlResults, setSqlResults] = useState('');

  const handleConvert = async () => {
    try {
      if (conversionType === 'json-to-csv') {
        const data = JSON.parse(input);
        const csv = Papa.unparse(data);
        setOutput(csv);
      } else if (conversionType === 'csv-to-json') {
        const parsed = Papa.parse(input, { header: true, skipEmptyLines: true });
        setOutput(JSON.stringify(parsed.data, null, 2));
      } else if (conversionType === 'json-to-xml') {
        const data = JSON.parse(input);
        const builder = new XMLBuilder({ format: true });
        const xml = builder.build({ root: data });
        setOutput(xml);
      } else if (conversionType === 'xml-to-json') {
        const parser = new XMLParser();
        const json = parser.parse(input);
        setOutput(JSON.stringify(json, null, 2));
      } else if (conversionType === 'html-to-markdown') {
        const turndownService = new TurndownService();
        setOutput(turndownService.turndown(input));
      } else if (conversionType === 'markdown-to-html') {
        const html = await marked.parse(input);
        setOutput(html);
      } else {
        setOutput('Conversion not implemented yet.');
      }
    } catch (e: any) {
      setOutput(`Error: ${e.message}`);
    }
  };

  const handleRunQuery = async () => {
    try {
      const res = await fetch('/api/db/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: sqlQuery })
      });
      const data = await res.json();
      if (data.error) {
        setSqlResults(`Error: ${data.error}`);
      } else {
        setSqlResults(JSON.stringify(data.results, null, 2));
      }
    } catch (e: any) {
      setSqlResults(`Error: ${e.message}`);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 p-6 overflow-y-auto">
      <h1 className="text-2xl font-semibold mb-6 flex items-center gap-2">
        <Database className="text-blue-500" /> Data Tools & Conversions
      </h1>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 flex-1">
        <div className="flex flex-col gap-2">
          <label className="text-sm font-medium text-zinc-500 dark:text-zinc-400">Input</label>
          <textarea 
            value={input}
            onChange={e => setInput(e.target.value)}
            className="flex-1 p-3 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-sm"
            placeholder="Paste your data here..."
          />
        </div>
        
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium text-zinc-500 dark:text-zinc-400">Output</label>
            <div className="flex items-center gap-2">
              <select 
                value={conversionType} 
                onChange={e => setConversionType(e.target.value)}
                className="text-sm bg-zinc-100 dark:bg-zinc-800 border-none rounded px-2 py-1 focus:ring-0"
              >
                <option value="json-to-csv">JSON to CSV</option>
                <option value="csv-to-json">CSV to JSON</option>
                <option value="json-to-xml">JSON to XML</option>
                <option value="xml-to-json">XML to JSON</option>
              </select>
              <button 
                onClick={handleConvert}
                className="flex items-center gap-1 bg-blue-600 hover:bg-blue-700 text-white px-3 py-1 rounded text-sm transition-colors"
              >
                Convert <ArrowRight size={14} />
              </button>
            </div>
          </div>
          <textarea 
            value={output}
            readOnly
            className="flex-1 p-3 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg resize-none focus:outline-none font-mono text-sm"
            placeholder="Converted data will appear here..."
          />
        </div>
      </div>
      
      <div className="mt-8">
        <h2 className="text-lg font-medium mb-4">Database Management</h2>
        <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-4">
          Run raw SQL queries against your local SQLite database (notebooks, sources, notes, workflows).
        </p>
        <div className="bg-zinc-100 dark:bg-zinc-800 p-4 rounded-lg border border-zinc-200 dark:border-zinc-700">
          <div className="flex gap-2 mb-2">
            <input 
              type="text" 
              value={sqlQuery}
              onChange={e => setSqlQuery(e.target.value)}
              placeholder="SELECT * FROM sources LIMIT 5;"
              className="flex-1 bg-white dark:bg-zinc-900 border border-zinc-300 dark:border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
            />
            <button 
              onClick={handleRunQuery}
              className="bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-4 py-2 rounded text-sm font-medium"
            >
              Run Query
            </button>
          </div>
          <textarea 
            readOnly
            value={sqlResults}
            className="w-full h-40 bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-700 rounded p-2 overflow-auto font-mono text-xs text-zinc-500 resize-none focus:outline-none"
            placeholder="Query results will appear here..."
          />
        </div>
      </div>
    </div>
  );
}
