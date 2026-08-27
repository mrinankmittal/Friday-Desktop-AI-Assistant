window.addEventListener("load", canvasApp);

// Change this to control the particle sphere size
let sphereRad = 105;

// Controls the perspective size
let radiusScale = 1;

function canvasApp() {
    const canvas = document.getElementById("canvasOne");

    if (!canvas || !canvas.getContext) {
        console.error("Canvas is not supported or canvasOne was not found.");
        return;
    }

    const context = canvas.getContext("2d");

    const displayWidth = canvas.width;
    const displayHeight = canvas.height;

    // Particle colour: green
    const particleRed = 0;
    const particleGreen = 255;
    const particleBlue = 0;

    const rgbString =
        `rgba(${particleRed}, ${particleGreen}, ${particleBlue},`;

    const particleAlpha = 1;
    const particleRadius = 1.8;

    // Perspective
    const focalLength = 320;
    const projectionCenterX = displayWidth / 2;
    const projectionCenterY = displayHeight / 2;
    const maximumZ = focalLength - 2;

    // Sphere position
    const sphereCenterY = 0;
    let sphereCenterZ = -3 - sphereRad;

    // Particle animation settings
    const particlesPerFrame = 8;

    const randomAccelerationX = 0.1;
    const randomAccelerationY = 0.1;
    const randomAccelerationZ = 0.1;

    const gravity = 0;
    const zeroAlphaDepth = -750;

    let turnAngle = 0;
    const turnSpeed = (2 * Math.PI) / 1200;

    const particleList = {
        first: null
    };

    const recycleBin = {
        first: null
    };

    function createParticles() {
        for (let i = 0; i < particlesPerFrame; i++) {
            const theta = Math.random() * 2 * Math.PI;
            const phi = Math.acos(Math.random() * 2 - 1);

            const x = sphereRad * Math.sin(phi) * Math.cos(theta);
            const y = sphereRad * Math.sin(phi) * Math.sin(theta);
            const z = sphereRad * Math.cos(phi);

            const particle = addParticle(
                x,
                sphereCenterY + y,
                sphereCenterZ + z,
                0.002 * x,
                0.002 * y,
                0.002 * z
            );

            particle.attack = 50;
            particle.hold = 50;
            particle.decay = 100;

            particle.initialAlpha = 0;
            particle.holdAlpha = particleAlpha;
            particle.finalAlpha = 0;

            particle.stuckTime = 90 + Math.random() * 20;

            particle.accelerationX = 0;
            particle.accelerationY = gravity;
            particle.accelerationZ = 0;
        }
    }

    function animate() {
        /*
         * Clear the previous frame.
         *
         * Do not use fillRect() here because it produces
         * a solid rectangular canvas background.
         */
        context.clearRect(0, 0, displayWidth, displayHeight);

        createParticles();

        turnAngle = (turnAngle + turnSpeed) % (2 * Math.PI);

        const sineAngle = Math.sin(turnAngle);
        const cosineAngle = Math.cos(turnAngle);

        let particle = particleList.first;

        while (particle !== null) {
            const nextParticle = particle.next;

            particle.age++;

            if (particle.age > particle.stuckTime) {
                particle.velocityX +=
                    particle.accelerationX +
                    randomAccelerationX * (Math.random() * 2 - 1);

                particle.velocityY +=
                    particle.accelerationY +
                    randomAccelerationY * (Math.random() * 2 - 1);

                particle.velocityZ +=
                    particle.accelerationZ +
                    randomAccelerationZ * (Math.random() * 2 - 1);

                particle.x += particle.velocityX;
                particle.y += particle.velocityY;
                particle.z += particle.velocityZ;
            }

            // Rotate the particle around the vertical axis
            const rotatedX =
                cosineAngle * particle.x +
                sineAngle * (particle.z - sphereCenterZ);

            const rotatedZ =
                -sineAngle * particle.x +
                cosineAngle * (particle.z - sphereCenterZ) +
                sphereCenterZ;

            // Perspective projection
            const perspectiveScale =
                (radiusScale * focalLength) /
                (focalLength - rotatedZ);

            particle.projectedX =
                rotatedX * perspectiveScale + projectionCenterX;

            particle.projectedY =
                particle.y * perspectiveScale + projectionCenterY;

            updateParticleAlpha(particle);

            const outsideCanvas =
                particle.projectedX > displayWidth ||
                particle.projectedX < 0 ||
                particle.projectedY > displayHeight ||
                particle.projectedY < 0 ||
                rotatedZ > maximumZ;

            if (outsideCanvas || particle.dead) {
                recycleParticle(particle);
            } else {
                drawParticle(
                    particle,
                    rotatedZ,
                    perspectiveScale
                );
            }

            particle = nextParticle;
        }

        requestAnimationFrame(animate);
    }

    function updateParticleAlpha(particle) {
        const attackEnd = particle.attack;
        const holdEnd = particle.attack + particle.hold;
        const decayEnd =
            particle.attack + particle.hold + particle.decay;

        if (particle.age < attackEnd) {
            particle.alpha =
                ((particle.holdAlpha - particle.initialAlpha) /
                    particle.attack) *
                    particle.age +
                particle.initialAlpha;
        } else if (particle.age < holdEnd) {
            particle.alpha = particle.holdAlpha;
        } else if (particle.age < decayEnd) {
            particle.alpha =
                ((particle.finalAlpha - particle.holdAlpha) /
                    particle.decay) *
                    (particle.age - particle.attack - particle.hold) +
                particle.holdAlpha;
        } else {
            particle.dead = true;
        }
    }

    function drawParticle(particle, rotatedZ, perspectiveScale) {
        let depthAlpha = 1 - rotatedZ / zeroAlphaDepth;

        depthAlpha = Math.max(0, Math.min(1, depthAlpha));

        const finalAlpha = depthAlpha * particle.alpha;

        context.fillStyle = `${rgbString}${finalAlpha})`;

        context.beginPath();

        context.arc(
            particle.projectedX,
            particle.projectedY,
            Math.max(0.5, perspectiveScale * particleRadius),
            0,
            2 * Math.PI
        );

        context.closePath();
        context.fill();
    }

    function addParticle(
        x,
        y,
        z,
        velocityX,
        velocityY,
        velocityZ
    ) {
        let newParticle;

        // Reuse an old particle when possible
        if (recycleBin.first !== null) {
            newParticle = recycleBin.first;

            recycleBin.first = newParticle.next;

            if (recycleBin.first !== null) {
                recycleBin.first.previous = null;
            }
        } else {
            newParticle = {};
        }

        // Add particle to the beginning of the list
        newParticle.previous = null;
        newParticle.next = particleList.first;

        if (particleList.first !== null) {
            particleList.first.previous = newParticle;
        }

        particleList.first = newParticle;

        newParticle.x = x;
        newParticle.y = y;
        newParticle.z = z;

        newParticle.velocityX = velocityX;
        newParticle.velocityY = velocityY;
        newParticle.velocityZ = velocityZ;

        newParticle.age = 0;
        newParticle.alpha = 0;
        newParticle.dead = false;

        return newParticle;
    }

    function recycleParticle(particle) {
        // Remove from active particle list
        if (particle.previous !== null) {
            particle.previous.next = particle.next;
        } else {
            particleList.first = particle.next;
        }

        if (particle.next !== null) {
            particle.next.previous = particle.previous;
        }

        // Add to recycle bin
        particle.previous = null;
        particle.next = recycleBin.first;

        if (recycleBin.first !== null) {
            recycleBin.first.previous = particle;
        }

        recycleBin.first = particle;
    }

    animate();

    /*
     * Optional slider support.
     * This only runs if jQuery and jQuery UI are loaded.
     */
    if (
        window.jQuery &&
        typeof window.jQuery.fn.slider === "function"
    ) {
        const $ = window.jQuery;

        if ($("#slider-range").length) {
            $("#slider-range").slider({
                range: false,
                min: 20,
                max: 200,
                value: sphereRad,

                slide: function (event, ui) {
                    sphereRad = ui.value;
                    sphereCenterZ = -3 - sphereRad;
                }
            });
        }

        if ($("#slider-test").length) {
            $("#slider-test").slider({
                range: false,
                min: 0.5,
                max: 2,
                value: radiusScale,
                step: 0.01,

                slide: function (event, ui) {
                    radiusScale = ui.value;
                }
            });
        }
    }
}