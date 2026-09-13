import assert from 'node:assert/strict';
import test from 'node:test';
import { buildAgentMcpConfig } from '../src/services/desktop.ts';

test('Agent MCP JSON preserves Windows paths containing spaces and Chinese characters', () => {
  const executablePath = 'D:\\应用 数据\\B站舆论监测\\BiliOpinionMonitor-0.3.0-fix.exe';
  const databasePath = 'D:\\应用 数据\\B站舆论监测\\data\\agent-snapshots\\快照 01\\snapshot.sqlite3';
  const configuration = JSON.parse(buildAgentMcpConfig(executablePath, databasePath));

  assert.equal(configuration.mcpServers['bili-opinion-readonly'].command, executablePath);
  assert.deepEqual(configuration.mcpServers['bili-opinion-readonly'].args, ['--mcp-stdio']);
  assert.equal(configuration.mcpServers['bili-opinion-readonly'].env.BILI_MCP_DB_PATH, databasePath);
});
