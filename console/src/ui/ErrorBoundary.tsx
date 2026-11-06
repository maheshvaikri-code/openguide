import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Last line of defence: if a page throws while rendering (for example on data the proxy returned
 * in an unexpected shape), show what happened instead of a blank screen. Resets when `resetKey`
 * changes, so navigating to another page recovers.
 */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Console view failed to render", error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="panel state error" role="alert">
        <span className="glyph" aria-hidden="true">!</span>
        <h2>This view hit an unexpected problem</h2>
        <p>The data it received wasn't in a shape the Console understands. Nothing was changed. {this.state.error.message}</p>
        <button className="btn" onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    );
  }
}
