import { Component, type ErrorInfo, type ReactNode } from 'react';
import { reportDiagnosticError, type DiagnosticState } from '../services/devDiagnostics';

interface Props {
  children: ReactNode;
  diagnosticState?: DiagnosticState;
}

interface State {
  failed: boolean;
}

export default class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    reportDiagnosticError('react.error_boundary', error, info.componentStack || undefined, this.props.diagnosticState);
  }

  render(): ReactNode {
    if (this.state.failed) {
      return (
        <main role="alert">
          <h1>页面暂时无法显示</h1>
          <p>请刷新页面后重试；若问题持续出现，请检查本机服务是否正常运行。</p>
          <button type="button" onClick={() => window.location.reload()}>刷新页面</button>
        </main>
      );
    }
    return this.props.children;
  }
}
