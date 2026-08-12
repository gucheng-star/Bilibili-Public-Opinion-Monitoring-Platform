# 应用图标

`icon.ico` 是当前 Windows 便携版主程序图标，源设计保存在 `app-icon.svg`。其他 PNG、ICNS、Android 和 iOS 文件由 Tauri 图标命令生成，当前 Windows 单 EXE 发布不会使用移动端资源。

需要更新图标时，在 `frontend/` 中执行：

```powershell
pnpm exec tauri icon .\src-tauri\icons\app-icon.svg
```

更新后检查：

1. `src-tauri/icons/icon.ico` 存在并且可以正常打开。
2. 如果以后显式配置 `bundle.icon`，路径必须指向有效文件。
3. Windows `icon.ico` 能被 Rust release 构建读取。
4. 最终 EXE 的文件图标与应用窗口图标一致。
5. 不要把 `src-tauri/target/` 中的生成产物提交到 GitHub。
