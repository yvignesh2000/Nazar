import { Component } from 'react';
import './ErrorBoundary.css';

/**
 * React Error Boundary — catches JS errors in any child component tree
 * and renders a graceful fallback UI instead of a blank white screen.
 *
 * Usage:
 *   <ErrorBoundary>
 *     <MyPage />
 *   </ErrorBoundary>
 *
 *   Or with a custom fallback:
 *   <ErrorBoundary fallback={<div>Custom error UI</div>}>
 *     <MyPage />
 *   </ErrorBoundary>
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    this.setState({ errorInfo });
    // TODO: Send to error tracking service (Sentry, etc.)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="error-boundary">
          <div className="error-boundary__card">
            <div className="error-boundary__icon">⚠️</div>
            <h2 className="error-boundary__title">Something went wrong</h2>
            <p className="error-boundary__message">
              {this.state.error?.message || 'An unexpected error occurred.'}
            </p>
            {import.meta.env.DEV && this.state.errorInfo && (
              <details className="error-boundary__details">
                <summary>Technical details</summary>
                <pre>{this.state.errorInfo.componentStack}</pre>
              </details>
            )}
            <div className="error-boundary__actions">
              <button
                className="error-boundary__btn error-boundary__btn--primary"
                onClick={this.handleReset}
              >
                Try Again
              </button>
              <button
                className="error-boundary__btn error-boundary__btn--secondary"
                onClick={() => window.location.reload()}
              >
                Reload Page
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
