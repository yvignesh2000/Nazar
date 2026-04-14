import './Spinner.css';

export default function Spinner({ size = 32 }) {
  return (
    <div className="spinner-wrap">
      <div className="spinner" style={{ width: size, height: size }} />
    </div>
  );
}
