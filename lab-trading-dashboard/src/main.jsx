import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App.jsx';
import './index.css';

// BASE_URL is e.g. /lab_live/ on GitHub Pages so routes like /live-trade-view work under /lab_live/live-trade-view
const basename = (typeof import.meta !== 'undefined' && import.meta.env?.BASE_URL)
  ? import.meta.env.BASE_URL.replace(/\/$/, '')
  : '';

createRoot(document.getElementById('root')).render(
    <BrowserRouter basename={basename}>
      <App />
    </BrowserRouter>
);