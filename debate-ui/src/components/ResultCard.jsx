export function ResultCard({ title, right, children }) {
  return (
    <div className="card section">
      <div className="row" style={{justifyContent: 'space-between'}}>
        <h3 style={{margin: 0}}>{title}</h3>
        {right}
      </div>
      <div className="section">{children}</div>
    </div>
  )
}


