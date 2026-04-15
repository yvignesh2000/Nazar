import PageHeader from '../components/ui/PageHeader';
import './Legal.css';

export default function Terms() {
  return (
    <div className="page-content legal-page">
      <PageHeader title="Terms of Service" description="Last updated: April 2026" />

      <div className="legal-content">
        <section>
          <h2>1. Acceptance of Terms</h2>
          <p>
            By accessing or using Nazar ("the Service"), you agree to be bound by these Terms of Service.
            If you are using the Service on behalf of an organization, you represent that you have the authority
            to bind that organization.
          </p>
        </section>

        <section>
          <h2>2. Description of Service</h2>
          <p>
            Nazar is an AI-powered WhatsApp sales intelligence platform that provides:
          </p>
          <ul>
            <li>Automated conversation management via WhatsApp Business API.</li>
            <li>AI-generated responses using third-party language models.</li>
            <li>Contact and pipeline management (CRM functionality).</li>
            <li>Campaign management and template management.</li>
            <li>Analytics and business intelligence reporting.</li>
          </ul>
        </section>

        <section>
          <h2>3. User Accounts</h2>
          <ul>
            <li>You must provide accurate and complete information when creating an account.</li>
            <li>You are responsible for maintaining the security of your credentials.</li>
            <li>You must notify us immediately of any unauthorized access.</li>
            <li>One person or entity may not maintain more than one free account.</li>
          </ul>
        </section>

        <section>
          <h2>4. Acceptable Use</h2>
          <p>You agree NOT to use the Service to:</p>
          <ul>
            <li>Send spam, unsolicited messages, or bulk promotional content without consent.</li>
            <li>Violate any applicable laws, regulations, or WhatsApp's policies.</li>
            <li>Impersonate any person or entity.</li>
            <li>Transmit malicious content, viruses, or harmful code.</li>
            <li>Attempt to access other users' data or workspaces.</li>
            <li>Use the AI to generate illegal, harmful, or deceptive content.</li>
            <li>Exceed your plan's usage limits through automated means.</li>
          </ul>
        </section>

        <section>
          <h2>5. WhatsApp Compliance</h2>
          <p>
            You are responsible for complying with WhatsApp's Business Policy and Commerce Policy.
            This includes obtaining proper consent before messaging contacts, respecting opt-out
            requests, and using approved message templates for outbound communication.
          </p>
        </section>

        <section>
          <h2>6. Billing & Payments</h2>
          <ul>
            <li>Free tier is available with usage limits as described in pricing.</li>
            <li>Paid plans are billed monthly or annually as selected.</li>
            <li>Upgrades take effect immediately; downgrades at the end of the billing period.</li>
            <li>Failed payments may result in service suspension after a grace period.</li>
            <li>Refunds are handled on a case-by-case basis within 30 days.</li>
          </ul>
        </section>

        <section>
          <h2>7. Data Ownership</h2>
          <ul>
            <li>You retain ownership of all content and data you upload to the Service.</li>
            <li>You grant us a limited license to process your data as needed to provide the Service.</li>
            <li>We do not claim ownership of your contacts, conversations, or business data.</li>
            <li>You may export or delete your data at any time.</li>
          </ul>
        </section>

        <section>
          <h2>8. AI-Generated Content</h2>
          <p>
            The Service uses third-party AI models to generate message responses.
            While we strive for accuracy, AI-generated content may occasionally be incorrect
            or inappropriate. You are responsible for reviewing automated responses and
            maintaining appropriate human oversight through the handoff system.
          </p>
        </section>

        <section>
          <h2>9. Service Availability</h2>
          <p>
            We aim for high availability but do not guarantee uninterrupted service.
            The Service depends on third-party APIs (WhatsApp, AI providers) which may
            experience their own outages. We will communicate planned maintenance in advance.
          </p>
        </section>

        <section>
          <h2>10. Limitation of Liability</h2>
          <p>
            To the maximum extent permitted by law, Nazar shall not be liable for any indirect,
            incidental, special, or consequential damages arising from your use of the Service,
            including but not limited to lost profits, lost sales, or data loss.
          </p>
        </section>

        <section>
          <h2>11. Termination</h2>
          <ul>
            <li>You may cancel your account at any time from the Billing page.</li>
            <li>We may suspend or terminate accounts that violate these terms.</li>
            <li>Upon termination, you may request data export within 30 days.</li>
          </ul>
        </section>

        <section>
          <h2>12. Changes to Terms</h2>
          <p>
            We may modify these terms at any time. Material changes will be communicated
            30 days in advance. Continued use after changes constitutes acceptance.
          </p>
        </section>

        <section>
          <h2>13. Contact</h2>
          <p>
            For questions about these terms, contact us at{' '}
            <a href="mailto:legal@nazar.app">legal@nazar.app</a>.
          </p>
        </section>
      </div>
    </div>
  );
}
