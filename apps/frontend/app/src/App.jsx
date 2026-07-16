import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AppProvider } from './contexts/index';
import Landing from './pages/Landing';
import Dashboard from './pages/Dashboard';
import Workspace from './pages/Workspace';
import AlertContainer from './components/Alert';

// configure root path 
const basename = import.meta.env.BASE_URL?.replace(/\/+$/, '') || '/';

function App() {
  return (
    <Router basename={basename}>
      <AppProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/home" element={<Dashboard />} />
          <Route path="/workspace/:projectId" element={<Workspace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <AlertContainer />
      </AppProvider>
    </Router>
  );
}

export default App;
