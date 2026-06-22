import { useState } from 'react'
import { Header } from '@/components/Header'
import { Home } from '@/pages/Home'
import { DocumentsPage } from '@/pages/DocumentsPage'
import { ConfigPage } from '@/pages/ConfigPage'
import { TestsPage } from '@/pages/TestsPage'
import { EvaluationPage } from '@/pages/EvaluationPage'
import { GraphPage } from '@/pages/GraphPage'

function App() {
  const [page, setPage] = useState('home')

  const renderPage = () => {
    switch (page) {
      case 'documents':
        return <DocumentsPage />
      case 'config':
        return <ConfigPage />
      case 'tests':
        return <TestsPage />
      case 'evaluation':
        return <EvaluationPage />
      case 'graph':
        return <GraphPage />
      default:
        return <Home />
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <Header page={page} onNavigate={setPage} />
      <main className="flex-1">
        {renderPage()}
      </main>
    </div>
  )
}

export default App
