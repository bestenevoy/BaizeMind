import { Routes, Route, Navigate } from 'react-router-dom'
import { Header } from '@/components/Header'
import { Home } from '@/pages/Home'
import { DocumentsPage } from '@/pages/DocumentsPage'
import { ConfigPage } from '@/pages/ConfigPage'
import { TestsPage } from '@/pages/TestsPage'
import { EvaluationPage } from '@/pages/EvaluationPage'
import { GraphPage } from '@/pages/GraphPage'

function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <Header />
      <main className="flex-1 min-h-0 overflow-hidden flex flex-col">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
          <Route path="/config" element={<ConfigPage />} />
          <Route path="/tests" element={<TestsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
