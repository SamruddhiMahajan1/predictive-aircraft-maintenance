import { hc } from '../../lib/colors.js';

// Labelled health bar (used for the sub-components of a part).
export default function SubBar({ name, h }) {
  return (
    <div className="blk" style={{ margin: '0 0 10px' }}>
      <div className="row" style={{ margin: 0 }}>
        <span>{name}</span>
        <span style={{ color: hc(h) }}>{Math.round(h * 100) + '%'}</span>
      </div>
      <div className="bar"><i style={{ width: h * 100 + '%', background: hc(h) }}></i></div>
    </div>
  );
}
