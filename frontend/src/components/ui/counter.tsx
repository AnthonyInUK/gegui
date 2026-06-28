import { useEffect } from 'react'
import { animate, useMotionValue, useTransform, motion } from 'framer-motion'

// 数字滚动动画
export function Counter({ value }: { value: number }) {
  const count = useMotionValue(0)
  const rounded = useTransform(count, (v) => Math.round(v).toLocaleString())
  useEffect(() => {
    const controls = animate(count, value, { duration: 1, ease: 'easeOut' })
    return controls.stop
  }, [value])
  return <motion.span>{rounded}</motion.span>
}
