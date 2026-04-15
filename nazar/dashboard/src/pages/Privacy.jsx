import { Shield } from 'lucide-react';
import PageHeader from '../components/ui/PageHeader';
import './Legal.css';

export default function Privacy() {
  return (
    <div className="page-content legal-page">
      <PageHeader title="Privacy Policy" description="Last updated: April 2026" />

      <div className="legal-content">
        <section>
          <h2>1. Information We Collect</h2>
          <p>
            When you use Nazar ("the Service"), we collect information you provide directly:
          </p>
          <ul>
            <li><strong>Account information</strong> — name, email address, and password when you create an account.</li>
            <li><strong>Business data</strong> — contacts, conversations, templates, pipeline data, and knowledge base content you add to the platform.</li>
            <li><strong>Usage data</strong> — interactions with the dashboard, feature usage, API calls, and analytics events.</li>
            <li><strong>Communication data</strong> — messages sent and received through WhatsApp Cloud API integration.</li>
          </ul>
        </section>

        <section>
          <h2>2. How We Use Your Information</h2>
          <ul>
            <li>Provide, maintain, and improve the Service.</li>
            <li>Process AI-powered message generation and conversation handling.</li>
            <li>Generate analytics, reports, and business insights.</li>
            <li>Send system notifications and service updates.</li>
            <li>Enforce our Terms of Service and protect against misuse.</li>
          </ul>
        </section>

        <section>
          <h2>3. Data Processing</h2>
          <p>
            Your conversation data is processed by third-party AI providers (such as OpenAI, Anthropic, Google, or OpenRouter)
            to generate automated responses. We send only the minimum context necessary for reply generation.
            We do not sell your data to third parties.
          </p>
        </section>

        <section>
          <h2>4. Data Storage & Security</h2>
          <ul>
            <li>All data is stored in your workspace's isolated environment.</li>
            <li>Passwords are hashed using PBKDF2-SHA256 with unique salts.</li>
            <li>API keys are stored server-side and never exposed to the frontend.</li>
            <li>Session tokens are HMAC-signed and time-limited.</li>
            <li>We use HTTPS for all data transmission.</li>
          </ul>
        </section>

        <section>
          <h2>5. Data Retention</h2>
          <p>
            We retain your data for as long as your account is active. You may request data export or deletion at any time.
            After account deletion, data is purged within 30 days from active systems and within 90 days from backups.
          </p>
        </section>

        <section>
          <h2>6. Your Rights</h2>
          <ul>
            <li><strong>Access</strong> — request a copy of all data we hold about you.</li>
            <li><strong>Correction</strong> — update inaccurate information.</li>
            <li><strong>Deletion</strong> — request complete removal of your data.</li>
            <li><strong>Export</strong> — download your contacts, conversations, and templates.</li>
            <li><strong>Opt-out</strong> — disable analytics tracking or AI processing.</li>
          </ul>
        </section>

        <section>
          <h2>7. Third-Party Services</h2>
          <p>The Service integrates with:</p>
          <ul>
            <li><strong>WhatsApp Cloud API</strong> (Meta) — for message delivery.</li>
            <li><strong>AI providers</strong> (OpenRouter, Anthropic, Google) — for response generation.</li>
            <li><strong>Stripe</strong> — for payment processing (if applicable).</li>
          </ul>
          <p>Each third-party service has its own privacy policy that governs their handling of data.</p>
        </section>

        <section>
          <h2>8. Cookies & Local Storage</h2>
          <p>
            We use browser local storage to maintain your session token and preferences.
            We do not use third-party tracking cookies or advertising pixels.
          </p>
        </section>

        <section>
          <h2>9. Changes to This Policy</h2>
          <p>
            We may update this policy from time to time. Material changes will be communicated
            via the dashboard or email. Continued use after changes constitutes acceptance.
          </p>
        </section>

        <section>
          <h2>10. Contact</h2>
          <p>
            For privacy-related questions or data requests, contact us at{' '}
            <a href="mailto:privacy@nazar.app">privacy@nazar.app</a>.
          </p>
        </section>
      </div>
    </div>
  );
}
