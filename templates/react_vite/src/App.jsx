import React, { useState } from 'react';

export default function App() {
  const [count, setCount] = useState(0);

  return (
    <div style={{ fontFamily: 'sans-serif', padding: '2rem', textAlign: 'center' }}>
      <h1>React + Vite Project</h1>
      <p>Created autonomously by Flexie Dev Assistant.</p>
      <div style={{ marginTop: '1.5rem' }}>
        <button
          onClick={() => setCount((c) => c + 1)}
          style={{
            padding: '0.6rem 1.2rem',
            fontSize: '1rem',
            cursor: 'pointer',
            backgroundColor: '#0284c7',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
          }}
        >
          Count is {count}
        </button>
      </div>
    </div>
  );
}
