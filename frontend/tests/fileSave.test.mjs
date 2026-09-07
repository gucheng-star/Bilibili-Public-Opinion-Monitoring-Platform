import assert from 'node:assert/strict';
import test from 'node:test';
import { saveCsvFile } from '../src/utils/fileSave.ts';

const originalWindow = globalThis.window;

function restoreWindow() {
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
}

test('CSV 保存优先写入用户在标准另存为窗口选择的文件', async () => {
  const writes = [];
  globalThis.window = {
    showSaveFilePicker: async options => {
      assert.equal(options.suggestedName, '评论.csv');
      assert.deepEqual(options.types[0].accept, { 'text/csv': ['.csv'] });
      return {
        name: '组员选择的文件.csv',
        createWritable: async () => ({
          write: async data => { writes.push(await data.text()); },
          close: async () => { writes.push('closed'); },
        }),
      };
    },
  };
  try {
    const result = await saveCsvFile('\uFEFF表头', '评论.csv');
    assert.deepEqual(result, {
      path: undefined,
    });
    assert.deepEqual(writes, ['表头', 'closed']);
  } finally {
    restoreWindow();
  }
});

test('取消另存为不会把取消动作显示为导出失败', async () => {
  globalThis.window = {
    showSaveFilePicker: async () => { throw new DOMException('cancelled', 'AbortError'); },
  };
  try {
    assert.equal(await saveCsvFile('内容', '评论.csv'), null);
  } finally {
    restoreWindow();
  }
});
