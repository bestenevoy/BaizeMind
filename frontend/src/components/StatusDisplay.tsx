import { Loader2, AlertCircle } from 'lucide-react'

export function LoadingSpinner() {
  return (
    <div className="flex justify-center py-12">
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
    </div>
  )
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="p-3 rounded-md bg-destructive/10 text-destructive text-sm flex items-center gap-2">
      <AlertCircle className="h-4 w-4 shrink-0" />
      {message}
    </div>
  )
}
