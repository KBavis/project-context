import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AppProvider } from './contexts/index';
import Home from './pages/Home';

function App() {
  return (
    <Router>
      <AppProvider>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/chat" element={<Home view="chat" />} />
          <Route path="/data-sources" element={<Home view="dataSources" />} />
          <Route path="/ingestion" element={<Home view="ingestion" />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppProvider>
    </Router>
  );
}

export default App;
