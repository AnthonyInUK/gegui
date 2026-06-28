import { motion } from 'framer-motion'
import { cn } from '../../lib/utils'

// Aceternity 风格 BackgroundGradient：动态渐变描边卡片
export function BackgroundGradient({
  children,
  className,
  containerClassName,
}: {
  children?: React.ReactNode
  className?: string
  containerClassName?: string
}) {
  const variants = {
    initial: { backgroundPosition: '0 50%' },
    animate: { backgroundPosition: ['0, 50%', '100% 50%', '0 50%'] },
  }
  return (
    <div className={cn('relative group p-[1px] rounded-2xl', containerClassName)}>
      <motion.div
        variants={variants}
        initial="initial"
        animate="animate"
        transition={{ duration: 6, repeat: Infinity, repeatType: 'reverse' }}
        style={{ backgroundSize: '300% 300%' }}
        className="absolute inset-0 rounded-2xl z-[1] opacity-50 group-hover:opacity-90 blur-sm transition duration-500 bg-[radial-gradient(circle_farthest-side_at_0_100%,#00ccb1,transparent),radial-gradient(circle_farthest-side_at_100%_0,#7b61ff,transparent),radial-gradient(circle_farthest-side_at_100%_100%,#ffc414,transparent),radial-gradient(circle_farthest-side_at_0_0,#1ca0fb,#141316)]"
      />
      <motion.div
        variants={variants}
        initial="initial"
        animate="animate"
        transition={{ duration: 6, repeat: Infinity, repeatType: 'reverse' }}
        style={{ backgroundSize: '300% 300%' }}
        className="absolute inset-0 rounded-2xl z-[1] bg-[radial-gradient(circle_farthest-side_at_0_100%,#00ccb1,transparent),radial-gradient(circle_farthest-side_at_100%_0,#7b61ff,transparent),radial-gradient(circle_farthest-side_at_100%_100%,#ffc414,transparent),radial-gradient(circle_farthest-side_at_0_0,#1ca0fb,#141316)]"
      />
      <div className={cn('relative z-10 rounded-[15px] bg-panel', className)}>{children}</div>
    </div>
  )
}
