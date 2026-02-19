import React from 'react';
import Button from '@mui/material/Button';

const LiveTradeListViewComponent = ({ gridPreview, filterBar }) => (
  <div style={{ padding: '12px 16px', position: 'relative' }}>
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, marginBottom: 8, width: '100%', minWidth: 0 }}>
      {/* Grid preview */}
      <div style={{ minWidth: 220, minHeight: 180 }}>
        {gridPreview}
      </div>
      {/* Responsive Filter bar */}
      {/* Removed left margin/minWidth from filter bar */}
      <div style={{ flex: 1, minWidth: 0, maxWidth: '100%', overflowX: 'auto', background: 'rgba(255,255,255,0.04)', borderRadius: 16, border: '1.5px solid #333', padding: 8, marginLeft: 0 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, width: '100%', minWidth: 0 }}>
          {filterBar}
        </div>
      </div>
    </div>
    </div>
  );

export default LiveTradeListViewComponent; 