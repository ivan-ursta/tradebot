import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Sidebar } from './components/layout/Sidebar';
import { Overview } from './pages/Overview';
import { Positions } from './pages/Positions';
import { TradeHistory } from './pages/TradeHistory';
import { EquityChartPage } from './pages/EquityChartPage';
import { SignalsFeed } from './pages/SignalsFeed';
import { ConfigPanel } from './pages/ConfigPanel';
import { Strategies } from './pages/Strategies';
import { Settings } from './pages/Settings';
import { ChartPage } from './pages/ChartPage';
import { BacktestPage } from './pages/BacktestPage';

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-gray-100">
        <Sidebar />
        <main className="flex-1 p-6 overflow-auto flex flex-col">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/positions" element={<Positions />} />
            <Route path="/trades" element={<TradeHistory />} />
            <Route path="/equity" element={<EquityChartPage />} />
            <Route path="/signals" element={<SignalsFeed />} />
            <Route path="/config" element={<ConfigPanel />} />
            <Route path="/strategies" element={<Strategies />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/chart" element={<ChartPage />} />
            <Route path="/backtest" element={<BacktestPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

