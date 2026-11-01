import { createRoot } from 'react-dom/client';
import App from './App';
import './i18n';
import './styles/index.css';
import { installPointerSheen } from './utils/pointerSheen';

installPointerSheen();

createRoot(document.getElementById('root')!).render(<App />);
