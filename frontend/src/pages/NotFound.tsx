import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { ru } from '@/ru'

export default function NotFound() {
  return (
    <section className="mx-auto flex max-w-md flex-col items-center gap-4 py-16 text-center">
      <p className="mono text-6xl text-brass">404</p>
      <h1 className="text-3xl">{ru.notFound.title}</h1>
      <Button asChild>
        <Link to="/">{ru.notFound.back}</Link>
      </Button>
    </section>
  )
}
